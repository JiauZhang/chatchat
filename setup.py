from setuptools import setup, find_packages

setup(
    name = 'chatchat',
    packages = find_packages(exclude=['examples']),
    version = '0.0.3',
    license = 'GPL-2.0',
    description = 'large language model api',
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
        'httpx', 'websocket-client',
    ],
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Programming Language :: Python :: 3.8',
    ],
)