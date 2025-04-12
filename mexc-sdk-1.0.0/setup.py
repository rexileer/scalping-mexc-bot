import json
import setuptools

kwargs = json.loads(
    """
{
    "name": "mexc-sdk",
    "version": "1.0.0",
    "description": "mexc sdk",
    "license": "ISC",
    "url": "https://github.com/mxcdevelop/mexc-api-sdk#readme",
    "long_description_content_type": "text/markdown",
    "author": "MEXC<suggest@mexc.com>",
    "bdist_wheel": {
        "universal": true
    },
    "project_urls": {
        "Source": "git+https://github.com/mxcdevelop/mexc-api-sdk.git"
    },
    "package_dir": {
        "": "src"
    },
    "packages": [
        "mexc_sdk",
        "mexc_sdk._jsii"
    ],
    "package_data": {
        "mexc_sdk._jsii": [
            "mexc-sdk@1.0.0.jsii.tgz"
        ],
        "mexc_sdk": [
            "py.typed"
        ]
    },
    "python_requires": ">=3.6",
    "install_requires": [
        "jsii>=1.44.1, <2.0.0",
        "publication>=0.0.3"
    ],
    "classifiers": [
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Typing :: Typed",
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved"
    ],
    "scripts": []
}
"""
)

with open("README.md", encoding="utf8") as fp:
    kwargs["long_description"] = fp.read()


setuptools.setup(**kwargs)
