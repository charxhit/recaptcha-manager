from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="recaptcha-manager",
    version="0.0.7",
    author="Charchit Agarwal",
    author_email="charchit.a00@gmail.com",
    url="https://www.github.com/charxhit/recaptcha-manager",
    description="Reduce waiting time for solving recaptchas to less than a second",
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: Microsoft :: Windows",
    ],
    python_requires='>=3.5',
    package_dir={'recaptcha_manager':'recaptcha_manager'},
    packages=['recaptcha_manager'],
    install_requires=['requests-futures >=1.0.0;platform_system=="Windows"',
                      'multiprocess;platform_system=="Windows"']
)
