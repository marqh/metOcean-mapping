from distutils.core import setup, Command
import os
import sys

import nose


class TestRunner(Command):
    description = 'Run the metOcean unit tests'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        lib_dir = os.path.join(sys.path[0], 'lib')
        modules = []
        for module in os.listdir(lib_dir):
            path = os.path.join(lib_dir, module)
            tests_path = os.path.join(path, 'tests')
            if path not in ['.git', '.svn'] and os.path.exists(tests_path):
                modules.append('{}.tests'.format(module))

        if not modules:
            raise ValueError('No tests were found to run.')

        n_processors = 1
        args = ['', 'module', '--processes={}'.format(n_processors),
                '--verbosity=2']

        success = True
        for module in modules:
            args[1] = module
            msg = 'Running test discovery on module {!r} with {} processor{}.'
            print
            print msg.format(module, n_processors,
                             's' if n_processors > 1 else '')
            print
            success &= nose.run(argv=args)
        if not success:
            exit(1)


setup(
    name='metOcean-mapping',
    version='0.1',
    description='Python packages for working with MetOcean MetaRelations',
    package_dir={'': 'lib'},
    packages=['metocean'],
    author='marqh',
    author_email='marqh@metarelate.net',
    cmdclass={'test': TestRunner},
    )
