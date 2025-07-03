from setuptools import setup, find_packages
from glob import glob
import os

package_name = 'rabbit'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(include=[package_name, f"{package_name}.*"]),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'msg'), glob('msg/*.msg')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Sergey Alekseev',
    maintainer_email='ser.alexeev@gmail.com',
    description='Robot Rabbit hybrid ROS 2 package',
    license='MIT',
    entry_points={
        'console_scripts': [
            'power_sensor = rabbit.power_sensor:main'
        ],
    },
)
