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












