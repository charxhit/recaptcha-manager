# recaptcha-manager
## _Reduce waiting time for solving recaptchas to less than a second_


Average solving time for recaptchas by solving services like 2Captcha, Anticaptcha, etc. is around 30-75s at best, which is often a bottleneck for most scripts relying on them. recaptcha-manager aims to alleviate this problem by truly "managing" your recaptcha solving needs without really changing how your script functions. It uses those same services, but with a non-blocking architecture and some derivative maths to bring the amount of time you have to wait for a recaptcha answer to less than a second. A brief run down of how it works is given below: 

1. **Efficient, non-blocking architecture**: Conventional approaches often require your script to wait for the captcha request to be registered and completely solved by the solving service before proceeding. This is not the case with recaptcha-manager. After your script signals that it wants more recaptchas to be solved (via a quick function call), the control is returned to it immediately. This is possible because the actual communication with the captcha solving service, including registering the captcha task and requesting it's answer, happens in a background process. 


2. **The Maths**: Recaptcha-manager can collect relevant statistics including how frequently your script requires recaptchas, the service's solving speed, the number being currently solved, and many more. It then mathematically analyses these factors to accurately predict how many captchas your script will require in the near future and automatically pre-sends those many requests to the captcha solving service whenever you request more recaptchas to be solved. What this results in is that whenever your program actually wants a recaptcha, there will be one already solved and available. It's worth adding that this mathematical analysis is very accurate and only uses recent statistics, which makes sure that the solved captchas won't expire due to more requests than required being sent to the solving service.


Here's a quick rundown of its other core features

- __Quick Integration__ - Supports API of popular captcha solving services like Anticaptcha, 2Captcha and CapMonster
- __Flexibility__ - Works equally well on applications requiring 2-3 captchas a minute as well as those requiring 40+ captchas a minute
- __Adaptability__ - Can readjust even if your applications' rate of requesting captchas drastically changes midway
- __Unification__ - If you use multiple captcha solving services, then you can use all of them simultaneously using recaptcha-manager, or switch between them incase of an error. 
- __Efficiency__ - Apart from sending HTTP requests to communicate with the solving service's API in a separate background process, the requests are also sent asynchronously so that the service response times do not slow down scripts requiring a high volume of recaptchas


However, recaptcha-manager is not suitable for all applications. Some things to keep in mind:
- Only supports Python 3.4 and above
- Only recaptcha-v2 and recaptcha-v3 are supported
- Only practical for use cases which repeatedly require captcha tokens for the same site

## Installation

You can install the package from pypi like below:
```python
pip install recaptcha_manager
```

## Usage / Documentation

Recaptcha-manager is relatively simple to integrate in any application. To familiarize yourself with all tools it offers, you can check out the [documentation](https://recaptcha-manager.readthedocs.io/en/latest/). 
Additionally, you can access full-code examples [here](https://github.com/charxhit/recaptcha-manager/tree/main/examples).

## Development

Want to contribute? Great!

Here are a few ways you can help:

- Report bugs that you come across
- Submit feature requests that you think would be helpful
- Star the project!

