from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="recaptcha-manager",                     # This is the name of the package
    version="0.0.1",                        # The initial release version
    author="Charchit Agarwal",                     # Full name of the author
    author_email="charchit.a00@gmail.com",
    url="https://www.github.com/charxhit/recaptcha-manager",
    description="Reduce waiting time for solving recaptchas to less than a second",
    long_description=long_description,      # Long description read from the the readme file
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: Microsoft :: Windows",
    ],                                      # Information to filter the project on PyPi website
    python_requires='>=3.5',                # Minimum version requirement of the package
    py_modules=["manager", "exceptions", "services", "generators"],             # Name of the python package
    package_dir={'':'recaptcha_manager'},     # Directory of the source code of the package
    install_requires=['requests-futures >=1.0.0;platform_system=="Windows"',
                      'multiprocess;platform_system=="Windows"']                     # Install other dependencies if any
)