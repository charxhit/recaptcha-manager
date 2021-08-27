# recaptcha-manager
## _Reduce waiting time for solving recaptchas to less than a second_


recaptcha-manager is a python package which handles the requesting and solving of google recaptchas according to the usage of your particular application. More specifically, it mathematically analyses relevant factors to pre-send captcha requests to solving services in the background such that whenever you request a captcha, there is already one ready. Since this pre-sending is adapted to your application's captcha usage statistics, it can make accurate predictions so that there won't be any expired captchas as an expense for the low waiting time. 

Here's a quick rundown of its other core features

- __Quick Integration__ - Supports API of popular captcha solving services like Anticaptcha and 2Captcha
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
For complete examples of how to use this, check out the [documentation](https://recaptcha-manager.readthedocs.io/en/latest/)

## Development

Want to contribute? Great!

Here are a few ways you can help:

- Report bugs that you come across
- Help integrate API of other captcha solving services (documentation to help do that will be updated soon)
- Submit feature requests that you think would be helpful
