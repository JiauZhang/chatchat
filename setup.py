from setuptools import setup, find_packages
from chatchat.version import __version__

setup(
    name = 'chatchat',
    packages = find_packages(exclude=['examples']),
    version = __version__,
    license = 'GPL-2.0',
    description = 'Large Language Models Python API ',
    author = 'JiauZhang',
    author_email = 'jiauzhang@163.com',
    url = 'https://github.com/JiauZhang/chatchat',
    long_description=open("README.md", "r", encoding="utf-8").read(),
    long_description_content_type = 'text/markdown',
    keywords = [
        'llm',
        'chatapi',
        'chatbot',
    ],
    install_requires=[
        'conippets >= 0.1.1', 'httpx',
    ],
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 3.8',
    ],
    entry_points = {
        'console_scripts': ['chatchat=chatchat.__main__:main'],
    },
)