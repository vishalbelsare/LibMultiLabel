import sys
import os
sys.path.insert(1, os.path.join(sys.path[0], '..', '..'))
import main

class FakeParser(dict):
    def __init__(self):
        self.flags = []

    def add_argument(self,
                     *args,
                     type=None,
                     default=None,
                     help=None,
                     action=None,
                     choices=None,
                     nargs=None,
                     const=None):
        flag = {'name': ' '.join(list(args)).replace('--', r'\-\-')}

        help = help.replace('%(default)s', str(default))
        help = help.replace('%(const)s', str(const))
        if choices:
            flag['description'] = f'{help}. One of {{{", ".join(choices)}}}.'
        else:
            flag['description'] = f'{help}.'

        self.flags.append(flag)


parser = FakeParser()
# Keep this line in sync with the same one in main.py:get_config()
parser.add_argument('-c', '--config', help='Path to configuration file')
main.add_all_arguments(parser)


def width(key):
    return max(map(lambda f: len(f[key]), parser.flags))

wn = width('name')
wd = width('description')

print("""..
    Do not modify this file. This file is generated by genflags.py.\n""")
print('='*wn, '='*wd)
print('Name'.ljust(wn), 'Description'.ljust(wd))
print('='*wn, '='*wd)
for flag in parser.flags:
    print(flag['name'].ljust(wn), flag['description'].ljust(wd))
print('='*wn, '='*wd)
