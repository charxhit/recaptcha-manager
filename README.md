# recaptcha-manager
## _Reduce waiting time for solving recaptchas to less than a second_


recaptcha-manager is a python package which handles the requesting and solving of google recaptchas according to the usage of your particular application. More specifically, it mathematically analyses relevant factors to pre-send captcha requests to solving services in the background such that whenever you request a captcha, there is already one ready. Since this pre-sending is adapted to your application's captcha usage statistics, it can make accurate predictions so that there won't be any expired captchas as an expense for the low waiting time. 

Here's a quick rundown of its other core features

- __Quick Integration__ - Supports API of popular captcha solving services like Anticaptcha, 2Captcha and CapMonster
- __Flexibility__ - Works equally well on applications requiring 2-3 captchas a minute as well as those requiring 40+ captchas a minute
- __Adaptability__ - Can readjust even if your applications' rate of requesting captchas drastically changes midway
- __Unification__ - If you use multiple captcha solving services, then you can use all of them simultaneously using recaptcha-manager, or switch between them incase of an error. 

However, recaptcha-manager is not suitable for all applications. Some things to keep in mind:
- Only supports Python 3
- Only recaptcha-v2 and recaptcha-v3 are supported
- Only practical for use cases which repeatedly require captcha tokens for the same site

## Installation/Usage

You can install the package from pypi like below:
```python
pip install recaptcha_manager
```

Keep in mind that this package uses [multiprocessing](https://docs.python.org/3/library/multiprocessing.html), and hence your main code should be protected by a `if __name__ == "__main__"` clause. A very simple example of how to do this is given below:
```python
# Original code

def main():
    func()
    
def func():
    pass

# Not protected
main()
```


```python
# Edited code

def main():
    func()
    
def func():
    pass

# Protected!
if __name__ == "__main__":
    main()
```
recaptcha-manager uses a service process in the background to enable communication with your application and online solving services. Communication with your application is handled through a queue and a shared boolean flag. To start a service process:
```python
import recaptcha_manager
from recaptcha_manager import AntiCaptcha, TwoCaptcha, CapMonster

class MyAntiCaptcha(AntiCaptcha):
    pass

class MyTwoCaptcha(TwoCaptcha):
    pass
    
class MyCapMonster(CapMonster):
    pass
    
if __name__ == "__main__":
    api_key = 'xxxxxxxxxxxxxx'
    
    # Generate queue and flag 
    request_queue = recaptcha_manager.generate_queue()
    flag = recaptcha_manager.generate_flag()
    
    # Start service process
    proc = MyTwoCaptcha.spawn_process(flag, request_queue, api_key)
    
    # Alternatively, you can use other services as well:
    # proc = MyAnticaptcha.spawn_process(flag, request_queue, api_key)
    # proc = MyCapMonster.spawn_process(flag, request_queue, api_key)
```
To stop a service process, use the flag from which you created it:
```python
flag.value = False
proc.join()
```
Once a service process is running, create an AutoManager object for your particular captcha type using the queue you passed to the service process:
```python
# Basic congifuration for the captchas you want to solve
target_url = 'https://some.site'
target_sitekey = 'xxxxxxxxxxxx'
captcha_type = 'v2' # or 'v3'

# Create an AutoManager object passing the same queue you passed to the service process
inst = AutoManager.create(request_queue, target_url, target_sitekey, captcha_type)
```

Now you can finally send requests and recieve captcha tokens! 
To automatically send appropriate number of captcha requests to be solved, do:
```python
inst.send_request()
```
To recieve solved requests, do:
```python
inst.get_request()
```
Once you are done with the instance, call 
```python 
inst.stop()
```
This removes all requests which have not yet been registered with the captcha solving service and stops all future requests from being registered. All solved requests, or the ones which are registered and are being solved, continue to do so and can be retrieved through `inst.get_request()` as and when they are solved.

For complete examples of how to use this, check out the [documentation](https://recaptcha-manager.readthedocs.io/en/latest/)

## Development

Want to contribute? Great!

Here are a few ways you can help:

- Report bugs that you come across
- Help integrate API of other captcha solving services (documentation to help do that will be updated soon)
- Submit feature requests that you think would be helpful
- Star the project!
