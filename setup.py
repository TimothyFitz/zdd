from distutils.core import setup

setup(
    name='Zero Downtime Deploy',
    version='0.1dev',
    packages=['zdd',],
    scripts=['bin/zddeploy'],
    license='The MIT License',
    long_description=open('README').read(),
)