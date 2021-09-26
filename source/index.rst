.. recaptcha-manager documentation master file, created by
   sphinx-quickstart on Sun Aug 15 21:10:58 2021.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

recaptcha-manager — Introduction
=============================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:


Average solving time for recaptchas by services like 2Captcha, Anticaptcha, etc. is around
30-60s at best. By using this package, you can bring that down to less than 1s. It achieves this by mathematically analysing relevant factors to predict and send more than one request whenever you request a captcha. The number of requests made is such that it keeps the waiting time minimal all the while making sure that there won't be any expired captchas.

However, this package is not suitable for all programs. Keep in mind that this package works by pre-sending multiple captcha requests. Therefore, it only supports ``recaptcha-v2`` and ``recaptcha-v3`` and will only be practical for tasks that require recaptcha tokens repeatedly for the same site.

.. note:: This package is in active development. Bug reports and feature-requests appreciated!

.. note:: This package uses multiprocessing to spawn a service process which handles captcha requests in the background. Therefore, your main code must be under a ``if __name__ == "__main__"`` clause (check `multiprocessing programming guidelines <https://docs.python.org/3/library/multiprocessing.html#programming-guidelines>`_ to know more).



Quickstart Example
======================

To store data, and to calculate and predict the number of captcha requests to send, an :class:`~recaptcha_manager.AutoManager` object is created. To solve captcha requests from captcha services, a suitable subclass of :class:`~recaptcha_manager.BaseService` is used to create another process using :mod:`multiprocessing` (or `multiprocess <https://github.com/uqfoundation/multiprocess>`_, a fork of :mod:`multiprocessing`) which works in the background. Because they exist in separate processes, communication between them is handled through a :class:`multiprocessing.Queue`. To end the service process gracefully, a shared :mod:`ctypes` object is used as a flag. A trivial example to spawn a service process and get captcha tokens is shown below::

   import recaptcha_manager
   import queue
   from recaptcha_manager import Anticaptcha # or TwoCaptcha
   from recaptcha_manager import AutoManager


   class MyAntiCaptcha(AntiCaptcha):
      pass


   def worker(inst, num):
      for _ in num:

         # Predict number of captchas required based on current usage
         inst.send_request()

         # Receive a captcha token
         c = inst.get_request()
         print(c['answer'])

      # stop further production of captcha tokens
      inst.stop()

      # Captcha tokens which were already being solved before we called stop() would still be solved normally. So we
      # fetch those tokens in this block
      while True:
         try:
            c = inst.get_request()
            print(c['answer'])

         except queue.Empty:

            # Now we can be sure no more captcha tokens are going to be produced
            print('All captcha tokens have now been used!')
            break



   APIKey = ''
   target_url = ''
   target_sitekey = ''
   captcha_type = 'v2' # or 'v3'

   if __name__ == "__main__":

      # generate flag and queue
      request_queue = recaptcha_manager.generate_queue()
      flag = recaptcha_manager.generate_flag()

      # start service process
      service_proc = MyAnticaptcha.spawn_process(flag, request_queue, APIKey)

      # start manager process. Note that we pass the same queue that we passed to our server process!
      inst = AutoManager.create(request_queue, target_url, target_sitekey, captcha_type)

      # Now we are ready to receive recpatchas
      worker(inst, 10)

      flag.value = False
      service_proc.join()

.. note:: Currently, only Anticaptcha and 2Captcha services are supported

.. versionadded:: 0.0.2
   Added support for Capmonster service

.. py:currentmodule:: recaptcha_manager

Creating an :class:`~AutoManager`
====================================

An object of :class:`~AutoManager` should be created using the :meth:`~AutoManager.create` function. It returns a managed proxy of an object of :class:`AutoManager` which can be used similar to a normal instance. A plus of using a managed proxy is that it can share its state among different processes.

To analyse and predict the optimal number of captchas to send, use the :meth:`~AutoManager.send_request` method. It automatically sends the requests to the service process so they can be sent to captcha solving services. To get a captcha token, use the :meth:`~AutoManager.get_request` method. By default, it blocks until a captcha answer is available.

.. note:: As a best practice, you should always call :meth:`~AutoManager.send_request` everytime before you call :meth:`~AutoManager.get_request`

Keep in mind that the manager relies on captcha usage statistics collected overtime for your program to predict and send optimal number of captcha requests. Therefore, high block times for the first 5-6 captchas or so should be expected at the beginning when calling :meth:`AutoManager.get_request`. If this bothers you, then you can set the ``initial`` parameter to a suitable integer when calling :meth:`~AutoManager.send_request` or during creation of manager with :meth:`~AutoManager.create`.

When you no longer need new recaptcha tokens, you can call :meth:`~AutoManager.stop` after which no new captcha requests will be sent even if you use :meth:`~AutoManager.send_request`. However, requests already registered with the captcha service, or requests which were already solved, will not be affected. After calling :meth:`~AutoManager.stop()`, once all requests already being solved have been solved AND used, :meth:`~AutoManager.get_request` will return a :exc:`queue.Empty` error. This signals that no more requests can be sent or received by the instance.

Example code - For ``recaptcha-v3`` (check `Quickstart Example`_ for ``recaptcha-v2``)::

      if __name__ == "__main__":
         #
         # other code inside
         #

         # Note the initial parameter. We will send 4 captcha requests incase not enough usage stat available instead of default value of 1
         manager = recaptcha_manager.AutoManager.create(request_queue, url='https://site.domain/here', sitekey="recaptcha site-key", captcha_type='v3',action="recaptcha-action", min_score=0.5, initial=4)

         for _ in range(5)
            # Initial parameter can be overrided when sending requests
            manager.send_requests(initial=5)

            # Blocks until token available
            c = manager.get_request()
            print(f"Token value is : {c['answer']}")

         # No new requests are sent
         manager.stop()

         # Get all captcha requests which were already being solved until there are none left.
         while True:
            try:
               c = manager.get_request()
               print(f"Token value is : {c['answer']}")
            except queue.Empty:
               print('Task done!!')
               break



Spawning a Service process
===================================

Service processes act as an interface between your program and the captcha services. They can be created using :meth:`~BaseService.spawn_process`. This method is a wrapper which calls the :meth:`~BaseService.requests_manager` function in a separate process, and returns the process object. A shared ctypes object is used to control the flow of function from a parent process (see parameter ``flag`` of :meth:`~BaseService.spawn_process`). To create the flag and queue parameters, you can use :func:`~recaptcha_manager.generate_flag` and :func:`~recaptcha_manager.generate_queue` respectively. Moreover, because the function sends HTTP requests to captcha services (to register task/get captcha token) in a different process, a flexible way to handle connection errors is also implemented.

You can specify a callable which will be called everytime an exception occurs (see parameter ``exc_handler`` of :meth:`~BaseService.spawn_process`).  The exception is passed as a parameter to the callable. Therefore, you can then have your own code to handle the exception. By default, after the exception occurs and ``exc_handler`` has been called, the exception is raised to outer scope. If you have handled the exception in ``exc_handler`` and do not want it to be raised, then return a Truthy object in ``exc_handler`` and the exception will be ignored. Sample ``exc_handler``::

            import sys

            def exc_handler(exc):
                '''All errors except SomeNonFatalError will be raised!'''

                if isinstance(exc, SomeNonFatalError):
                    print('This error will be ignored!')
                    # #
                    # Some user-defined code to handle the error
                    ##
                    return True  # Because we return True, this error will not be raised!

                # Print out information about the error if its not SomeNonFatalError before its raised in outer scope
                print(sys.exc_info())


Additionally, you can pass a :class:`~urllib3.util.Retry` object which will be mounted to every outgoing request (see parameter ``retry`` in :meth:`~BaseService.spawn_process`)::

   from requests.packages.urllib3.util.retry import Retry

   retries = Retry(total=5, backoff_factor=1)

You can then pass this to the server process::

   service_proc = MyAntiCaptcha.spawn_process(flag, request_queue, APIKey, retry=retries, exc_handler=exc_handler)

Lastly, there may be times when you want to switch the service being used, or restart it, particularly if a :exc:`~recaptcha_manager.exceptions.LowBidError` or a :exc:`~recaptcha_manager.exceptions.NoBalanceError` was raised. To handle these cases, there needs to be a way to exit the current service process, and start a new one, with minimum loss of data in between. Therefore, to achieve this you should create your own wrapper to call :meth:`~BaseService.requests_manager` with appropriate error handling, and use :meth:`~BaseService.get_state` to pass the state of one service process onto another using the `state` parameter of :meth:`~BaseService.requests_manager`. Example code to demonstrate this::

   class MyAntiCaptcha(AntiCaptcha):
      pass

   class MyTwoCaptcha(TwoCaptcha):
      pass

   def my_wrapper_to_switch_service(flag, request_queue, key_anticaptcha, key_2captcha, **kwargs):
      # This wrapper switches service upon a NoBalanceError

      try:

         # This blocks until flag.value becomes False or an error is raised
         MyAntiCaptcha.requests_manager(flag, request_queue, key_anticaptcha, **kwargs)

      except recaptcha_manager.exceptions.NoBalanceError:
         # Get current state to minimize loss of data
         state = MyAntiCaptcha.get_state()

         # Start another service with the current state
         MyTwoCaptcha.requests_manager(flag, request_queue, key_2captcha, state=state, **kwargs)

   def my_wrapper_to_restart_service(flag, request_queue, key_anticaptcha, key_2captcha, **kwargs):
      # This wrapper restarts service after raising bid if it receives a LowBidError

      try:

         # This blocks until flag.value becomes False or an error is raised
         MyAntiCaptcha.requests_manager(flag, request_queue, key_anticaptcha, **kwargs)

      except recaptcha_manager.exceptions.LowBidError:
         ##
         # some code to increase bid
         ##

         state = MyAntiCaptcha.get_state()

         # Restart current service with the same state now that we have increased bid
         MyAntiCaptcha.requests_manager(flag, request_queue, key_anticaptcha, state=state, **kwargs)

   if __name__ == "__main__":
      ##
      # Previous code
      ##

      service_proc = multiprocessing.Process(target=my_wrapper_to_restart_service, args=(flag, request_queue, key), kwargs={'exc_handler':exc_handler})

      service_proc.start()

.. note:: If you switch captcha solving services then all tasks already registered with the previous service will be removed. This may not only lead to a monetary loss, but may also lead to longer wait times for a little while when requesting captchas.
.. note:: Certain callables, like lambda functions and class methods, are not picklable by :mod:`pickle` (for a full list of what can be pickled, check `this <https://docs.python.org/3/library/pickle.html#what-can-be-pickled-and-unpickled>`_). When creating your own wrapper, if you run into :exc:`~pickle.PicklingError` with the passed arguments, consider using `multiprocess <https://github.com/uqfoundation/multiprocess>`_, a fork of :mod:`multiprocessing` which uses :mod:`dill` to do the pickling. ``multiprocess`` has same syntax and functionality as :mod:`multiprocessing` but can pickle almost all objects using :mod:`dill`.

To quit a server process, simply set ``flag.value`` to False (see param ``flag`` of :meth:`~BaseService.spawn_process`) and wait for the process to quit like below::

   # signal service process to quit
   flag.value = False

   # blocks until service process quits
   service_proc.join()



References
============

This section contains all relevant code and its documentation separated by their classes

Service classes
---------------------
.. versionadded:: 0.0.2
   Added service class :class:`~recaptcha_manager.CapMonster`

All supported services and their base class.

BaseService
+++++++++++++++++++++
.. module:: recaptcha_manager

.. autoclass:: BaseService
   :members:

AntiCaptcha
++++++++++++++++++++++
.. autoclass:: AntiCaptcha
   :show-inheritance:

TwoCaptcha
+++++++++++++++++++++++
.. autoclass:: TwoCaptcha
   :show-inheritance:

CapMonster
+++++++++++++++++++++++
.. autoclass:: CapMonster
   :show-inheritance:

AutoManager class
---------------------
.. versionadded:: 0.0.2
   Method :meth:`~AutoManager.get_waiting_time`

.. autoclass:: AutoManager
   :members:
   :inherited-members:

Miscellaneous functions
------------------------

.. autofunction:: recaptcha_manager.generate_queue

.. autofunction:: recaptcha_manager.generate_flag

Exceptions
----------------

.. automodule:: recaptcha_manager.exceptions
   :members:

