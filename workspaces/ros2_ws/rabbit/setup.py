from setuptools import find_packages, setup

package_name = 'rabbit'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Sergey Alekseev',
    maintainer_email='ser.alexeev@gmail.com',
    description='Robot Rabbit Python nodes',
    license='MIT',
    entry_points={
        'console_scripts': [
            'power_sensor = rabbit.power_sensor:main',
        ],
    },
)