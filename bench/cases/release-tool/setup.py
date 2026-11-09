from setuptools import find_packages, setup

setup(name="release-tool", version="1.4.0", packages=find_packages(), entry_points={
    "console_scripts": ["release=release.cli:main"]})
