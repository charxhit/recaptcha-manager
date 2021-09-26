
from abc import ABC
import types
import time
import queue
import multiprocessing
from multiprocessing import Manager, Queue
from multiprocessing.managers import BaseManager, BaseProxy, NamespaceProxy


class ObjProxy(NamespaceProxy):
    """Returns a proxy instance for any user defined data-type. The proxy instance will have the namespace and
    functions of the data-type (except private/protected callables/attributes). Furthermore, the proxy will be
    pickable and can its state can be shared among different processes. """

    def __getattr__(self, name):
        result = super().__getattr__(name)
        if isinstance(result, types.MethodType):
            def wrapper(*args, **kwargs):
                return self._callmethod(name, args, kwargs)
            return wrapper
        return result


class BaseRequest(ABC):
    """Base class for managers"""

    def __init__(self, request_queue, maximum=0, initial=1, limit=0):

        assert isinstance(request_queue, BaseProxy), "Queues Passed to constructor should be proxy objects"
        assert initial > 0, " initial parameter cannot be 0 or less than 0"
        m = Manager()
        self.maximum = maximum
        self.initial = initial
        self.limit = limit
        self.response_queue = m.Queue()
        self.request_queue = request_queue
        self.instance_lock = m.Lock()
        self.ReqsUsed = 0
        self.ReqsSolved = 0
        self.WaitingTime = {'num': 0, 'total_time': 0, 'rate': 0.0}
        self.UseRate = {'num': 0, 'total_time': 0, 'last_time': time.time(), 'rate': 0.0}
        self.QToSolved = {'num': 0, 'total_time': 0, 'rate': 0.0}
        self.ReqsInUnsolvedList = 0
        self.ReqsInQueue = 0
        self.expired = 0
        self.proxy = None
        self.stop_new_requests = False
        self.finished = False

    @classmethod
    def create(cls, *args, **kwargs):
        """
        Properly initializes a class instance.

        :return : A proxy instance of class. Has same functionality as a regular instance and can share state between
                  processes.
        :rtype : ObjProxy
        """

        # Register class
        class_str = cls.__name__
        BaseManager.register(class_str, cls, ObjProxy, exposed=tuple(dir(cls)))

        # Start a manager process
        manager = BaseManager()
        manager.start()

        # Create and store instance. We must store this proxy instance since its passed in request_queue to another
        # process whenever a captcha request is required. This allows sharing of state between processes.
        inst = eval("manager.{}(*args, **kwargs)".format(class_str))
        inst.set_proxy(inst)

        return inst

    def set_proxy(self, proxy):
        """
        Set proxy for current instance which shares its state with other processes. We use this proxy to interact
        with other processes

        :meta private:
        """

        self.proxy = proxy

    def create_request(self):
        """
        Create correctly formatted request to be put into request_queue

        :return: Request ready to be put into request_queue
        :rtype: dict
        :meta private:
        """
        return {'instance': self.proxy, 'timeToQ': time.time()}

    def request_failed(self):
        """
        Called when a captcha request was unable to be solved.

        :meta private:
        """

        # Put another captcha request and in/decrement relevant counters
        self.request_queue.put(self.create_request())
        with self.instance_lock:
            self.ReqsInUnsolvedList -= 1
            self.ReqsInQueue += 1

    def get_upcoming(self):
        """
        Get how many captchas are being currently solved

       :rtype: int
       """

        return self.ReqsInQueue + self.ReqsInUnsolvedList

    def request_solved(self, timeToQ):
        """
        Called when a captcha request was successfully solved

        :param timeToQ: The time when the captcha request was sent to request_queue

        :meta private:
        """

        with self.instance_lock:
            self.ReqsInUnsolvedList -= 1

            # Add amount of time taken for captcha to move from request_queue to response_queue and increment solved
            # captchas counter
            self.QToSolved['num'] += 1
            self.QToSolved['total_time'] += time.time() - timeToQ
            self.ReqsSolved += 1

    def stop(self):
        """
        Stops production of new captcha requests. Requests already being solved won't be affected and captcha
        tokens for those requests will be produced normally. Should only be called when you no longer intend to send
        new requests.
        """

        with self.instance_lock:
            self.stop_new_requests = True

    def flush(self):
        """
        Remove all stored solved captchas (if any). Good for cleaning up after you are done with the instance
        """

        with self.instance_lock:
            while True:
                try:
                    self.response_queue.get(block=False)
                except queue.Empty:
                    break

    def get_waiting_time(self):
        """
        Returns recent average waiting time to receive a captcha token from server process. Will be zero if not enough
        statistics collected.

        :rtype: float
        """

        with self.instance_lock:
            self.update_stats()
        return self.WaitingTime['rate']

    def get_request(self, send_custom_reqs=True, max_block=0):
        """
        Returns a solved captcha. Blocks until one is ready

        :param bool send_custom_reqs: By default function will send additional captcha requests if there are none
                                      being solved. Set to False to prevent this
        :param int max_block: Maximum time the function blocks in seconds. Set as 0 to block until a request is recieved
        :return: A dictionary containing the token under key 'answer', or None if max_block was non-zero and time limit
                 was reached
        :rtype: dict

        :raises: :exc:`queue.Empty` - When production of captcha requests was stopped using instance.stop() and no new
                               requests are being currently solved.

        Example ::

            try:
                c = instance.get_request()  # Blocks until one is ready
            except queue.Empty:
                print('done')
            else:
                token = c['answer']

        .. warning::
            If ``send_custom_reqs`` is ``False``, then code may block indefinitely if there aren't any captcha requests
            being solved. In case it is set to ``False``, set ``max_block`` to a non zero value

        """
        assert max_block >= 0, f"{max_block} is not a valid value for parameter max_block"

        with self.instance_lock:

            # Check if no new captcha requests are going to be solved. If so, return None
            if self.stop_new_requests and self.ReqsInUnsolvedList + self.response_queue.qsize() == 0:
                self.finished = True
            if self.finished:
                raise queue.Empty

            # Record the time elapsed since last time get_request() was called to know how frequently does program
            # require captchas
            self.UseRate['num'] += 1
            self.UseRate['total_time'] += (time.time() - self.UseRate['last_time'])
            self.UseRate['last_time'] = time.time()

        enter_time = time.time()

        while True:

            if max_block and time.time() - enter_time >= max_block:

                # Update stats
                with self.instance_lock:

                    # We refresh the last call since we don't want to record the time spent within the function but
                    # the time between consecutive calls to get_request().
                    self.UseRate['last_time'] = time.time()

                return None

            try:
                c = self.response_queue.get(timeout=2)
            except queue.Empty:

                # If there were no captcha tokens available within 5 seconds, we check if stop_new_requests is False
                # and whether there are captcha requests being solved. If not, we raise queue.Empty error
                if self.stop_new_requests and self.response_queue.qsize() + self.ReqsInUnsolvedList == 0:
                    self.finished = True
                    raise queue.Empty

                # Otherwise, if stop_new_requests is False, then we manually send one request
                if not self.stop_new_requests and send_custom_reqs and self.ReqsInQueue + self.response_queue.qsize() + \
                        self.ReqsInUnsolvedList == 0:

                    # Increment counter since we are adding a request in request queue
                    with self.instance_lock:
                        self.ReqsInQueue += 1

                    # Add a request in request_queue
                    self.request_queue.put(self.create_request())
            else:
                # We got a captcha
                with self.instance_lock:
                    self.ReqsUsed += 1

                # Captcha is assumed to have NOT expired
                if time.time() - c['timeSolved'] < 120:

                    # Update stats
                    with self.instance_lock:

                        # Record the amount of time waited to receive captcha
                        time_waited = time.time() - enter_time
                        self.WaitingTime['num'] += 1
                        self.WaitingTime['total_time'] += time_waited

                        # We refresh the last call since we don't want to record the time spent within the function but
                        # the time between consecutive calls to get_request().
                        self.UseRate['last_time'] = time.time()

                    return c
                else:
                    # Captcha expired
                    self.expired += 1

    def update_stats(self):
        """
        Update the usage statistics when we need to use them

        :meta private:
        """

        # First we update WaitingTime['rate']. If the number of times get_request() waited for captcha is 0, then set
        # the rate as 0 as well
        if self.WaitingTime['num'] == 0:
            self.WaitingTime['rate'] = 0.0
        else:
            self.WaitingTime['rate'] = self.WaitingTime['total_time'] / self.WaitingTime['num']

        # Next we update UseRate['rate']. If the number of of captchas used is 0, then set the rate as 0 as well
        if self.UseRate['num'] == 0:
            self.UseRate['rate'] = 0.0
        else:
            # We check if total_time has been more than 150 seconds. This is to ensure we only have the most recent info
            # from last 120 seconds. We do this check at 150 seconds so that after old stats of previous 120s are
            # removed, we still have enough info to make accurate predictions
            if self.UseRate['total_time'] >= 150:

                # We then check based on current stats, how many solves will be done in 120s
                recent_num_solved = round(self.UseRate['num'] / self.UseRate['total_time'] * 120)

                # Since we want enough info after we remove the old stats, we check if there will be info about atleast
                # 5 solves
                if self.UseRate['num'] - recent_num_solved >= 5:
                    self.UseRate['num'] -= recent_num_solved
                    self.UseRate['total_time'] -= 120

            self.UseRate['rate'] = self.UseRate['total_time'] / self.UseRate['num']

        # We then update QToSolved['rate']. If the number of of captchas solved is 0, then set the rate as 0 as well
        if self.QToSolved['num'] == 0:
            self.QToSolved['rate'] = 0.0
        else:
            self.QToSolved['rate'] = self.QToSolved['total_time'] / self.QToSolved['num']

    def send_request(self, maximum=None, initial=None):
        """
        Predict and send optimal number of captcha requests to server process to minimize waiting time.

        :param int maximum: Maximum number of requests to send. Overrides value passed when creating instance
        :param int initial: Number of requests to send if there is not enough data to predict. Overrides value passed
                            when creating instance

        This function must be called periodically to ensure the least waiting time. A general rule is to call it
        every time before you call :meth:`~AutoManager.get_request()` function.
        """

        if not maximum: maximum = self.maximum
        if not initial: initial = self.initial

        # If number of captchas being solved are more or equal to limit, given limit is greater than 0, then we don't
        # send anymore requests
        if 0 < self.limit <= self.ReqsInUnsolvedList + self.ReqsInQueue:
            return

        # There should atleast be three captchas used for there to be adequate data for us to make predictions
        if self.ReqsUsed >= 3:

            # We try to predict how many requests we should send to achieve the least amount of waiting time for future
            # responses. We do this by predicting how many tokens will be available by the time a request sent now would
            # be solved and comparing that with the current usage data.
            with self.instance_lock:

                # This variable holds the amount of requests for captchas we will send. Initial value is 0.
                to_send = 0

                # Before doing any calculations, we update our collected data
                self.update_stats()

                # This is the amount of time a request sent now would take to be solved.
                final_time = self.QToSolved['rate']

                # Its a fair assumption that by the time this request will be added to the response queue, all requests
                # currently there in the request queue + unsolved list will be added as well. Therefore, final_time
                # seconds later, these all captchas will be added to the response queue
                to_add = self.ReqsInQueue + self.ReqsInUnsolvedList

                # Then we check how many caps will be used by then
                to_subtract = final_time // self.UseRate['rate']

                # We then find the amount of captchas in the response queue after final_time
                final_caps = self.response_queue.qsize() + to_add - to_subtract

                # Now we calculate the amount of time these captcha will require to be used up
                total_time = final_caps * self.UseRate['rate']

                # Now if the time to use them is below 30s, we can request more captchas to be added. To do this, we
                # calculate the optimal amount of captchas there should be after final_time seconds and send the
                # difference in the optimum and our calculated value.
                if total_time < 30:
                    optimal_final_caps = 30 // self.UseRate['rate']
                    if maximum:
                        to_send = min(optimal_final_caps - final_caps, maximum)
                    else:
                        to_send = optimal_final_caps - final_caps

        else:
            # If we don't have enough data, we simply send initial number of requests
            to_send = initial

        # If sending current number of requests exceeds limit, and limit is greater than 0, then we adjust to_send so
        # that it stays below limit
        if 0 < self.limit < to_send + self.ReqsInQueue + self.ReqsInUnsolvedList:
            to_send = self.limit - self.ReqsInQueue - self.ReqsInUnsolvedList

        # If after adjusting we get a zero or negative value, we return without sending any requests
        if to_send <= 0:
            return

        # Increment counter since we are going to be adding requests in request_queue
        with self.instance_lock:
            self.ReqsInQueue += to_send

        # Finally, add the calculated number of requests in queue
        for _ in range(int(round(to_send))):
            self.request_queue.put(self.create_request())

    def write_status(self):
        """
        Print out some basic statistics. Useful for debugging
        """

        with self.instance_lock:
            self.update_stats()
        print('             Captcha Manager')
        print('Total Captchas Solved                                              : {}'.format(self.ReqsSolved))
        print('Total Captchas Used                                                : {}'.format(self.ReqsUsed))
        print('Current amount of unused solved captchas                           : {}'.format(self.response_queue.qsize()))
        print('Current amount of captchas being solved                            : {}'.format(self.get_upcoming()))
        print('Avg time taken for ONE captcha to be processed and solved          : {}'.format(self.QToSolved['rate']))
        print('Avg time taken before a captcha is requested from Manager          : {}'.format(self.UseRate['rate']))
        print('Avg Waiting time for captcha to be available upon request          : {}'.format(self.WaitingTime['rate']))
        print('---------------------------------------------------------------------------------')


class AutoManager(BaseRequest):
    """
    Manages creation and sending of captcha requests to service process. Predicts the optimal number of captchas to
    send based on usage statistics.

    .. note::
        Do not call the constructor directly, instances should be created through :meth:`~AutoManager.create()` function

    Example instantiation::

       url = 'Target url'
       sitekey = 'Target site's sitekey'
       captcha_type = 'can be "v2" or "v3"'

       if __name__ == '__main__':
           request_queue = recaptcha_manager.generate_queue()
           instance = AutoManager.create(request_queue, url, sitekey, captcha_type)

    """

    def __init__(self, request_queue, url, web_key, captcha_type, action=None, min_score=None, invisible=False,
                 initial=1, maximum=0, limit=0):
        assert captcha_type in ['v2', 'v3'], "Captcha type {} not recognized. Only 'v2' and 'v3' google recaptchas " \
                                                 "are supported".format(captcha_type)

        if captcha_type == 'v3':
            assert action, "Action parameter cannot be left blank if captcha type is 'v3'"
            assert min_score, "min_score cannot be left blank if captcha type is 'v3'"
            assert 0 < min_score < 1, "Invalid min_score value provided"

        super().__init__(request_queue, maximum=maximum, initial=initial, limit=limit)
        self.invisible = invisible
        self.web_key = web_key
        self.url = url
        self.captcha_type = captcha_type
        self.action = action
        self.min_score = min_score

    @classmethod
    def create(cls, request_queue, url, web_key, captcha_type, action=None, min_score=None, invisible=False,
               initial=1, maximum=0, limit=0):
        """
        Properly initializes the constructor for AutoManager.

        :param multiprocessing.Queue request_queue: A queue for communication between service process and instances of
                                    AutoManager. Can be generated by :func:`recaptcha_manager.generate_queue()`

        :param str url: URL of target website
        :param str web_key: sitekey of target website
        :param str captcha_type: Version of recaptcha the target site uses. Can be 'v2' or 'v3'
        :param str action: Action parameter in case solving recaptcha v3
        :param float min_score: minimum score you want if solving recaptcha v3. Should be between 0 and 1
        :param bool invisible: Whether or not the target site uses invisible recaptcha v2
        :param int initial: Number of captcha requests to send when calling :meth:`~AutoManager.send_request` initially
                            when there isn't enough data. Defaults to 1
        :param int maximum: Maximum number of captcha requests to send on one call of :meth:`~AutoManager.send_request`
                            function. Set as 0 to specify no such limit.
        :param int limit: Maximum number of allowed captcha requests being solved at once. Set as 0 to disable this
                          limit

        :returns: A proxy instance of class AutoManager. Has same functionality as a regular instance
        :rtype: AutoManager

        The number of captchas requests to send are predicted on the basis of usage details only if sufficient number
        (3) of captchas have been solved and used. Until then, ``initial`` (default value 1) number of captchas will
        be sent on every call of :meth:`~AutoManager.send_request()` function.
        """

        return super().create(request_queue, url, web_key, captcha_type, action=action, min_score=min_score,
                              invisible=invisible, initial=initial, maximum=maximum, limit=limit)


def exc_handler(exc):
    print(exc)
