# Changelog
All notable changes to this project will be documented in this file. Dates in format dd/mm/yyyy


## [0.0.2] - 26-09-2021
### Added
- Method to get recent wait time
- Support for CapMonster service and relevant documentation
- Basic usage examples in the Readme file

### Fixed
- ImportError when importing the package
- Minor bugfixes due to spelling mistakes
- Variable naming inconsistencies in documentation

## [0.0.3] - 17-07-2022
### Added
- A new manager, ManualManager
- Support for retrieving exceptions raised in service process.
- Methods to retrieve statistics from AutoManager
- Expanded Tests for managers and services

### Fixed
- Exceptions raised due to faulty manager configuration are raised in the main process itself rather than the solving process.
- Minor bugfixes

### Removed
- Flags are no longer required to start service processes
- Passing of state between services is no longer allowed

Other, more specific and major semantic changes have been listed in the documentation [here](https://recaptcha-manager.readthedocs.io/en/latest/#version-0-0-3-backwards-compatibility)

## [0.0.4] - 19-07-2022
## Fixed
- TypeError when using a service
- Other minor bugs


## [0.0.5] - 19-07-2022
## Fixed
- Fixed bug which led to AttributeError when attempting to pass error raised from service process to manager
- Fixed formatting issues and erroneous docstrings
- Added soft_id parameter for 2Captcha

## [0.0.6] - 28-09-2022
## Removed 
- BaseService and BaseRequest no longer inherit from abc.ABC to create abstract classes. These changes will make subclasses picklable for further releases.

## [0.0.7] - 30-09-2022
## Added
- Subpackage `api` was added

## Fixed
- All proxy classes for services and managers are now picklable by standard pickle module

## Removed
- All modules within recaptcha-manager were relocated to `api` subpackage

## [0.0.8] 30-09-2022

## Added
- Submodule `configuration` was added to recaptcha_manager
- Ability for users to choose whether recaptcha_manager should use standard multiprocessing or multiprocess internally.

## [0.0.9] 01-10-2022

## Fixed
- SyntaxError in `generators.py` when run in Python3.8>










