import argparse
import os

from pprint import pformat
from termcolor import colored, cprint

from git import git_checkout, get_changed_files
from parser import FieldFinder

import consts


def main(branch, root):
    serializer_directory = os.path.join(root, 'apiv2/serializers')
    view_directory = os.path.join(root, 'apiv2/views')
    files = [os.path.join(root, 'apiv2/fields.py')]

    changed_files = get_changed_files(branch)

    current_ff = FieldFinder.crawl(
        serializer_directory, view_directory, files=files
    )

    with git_checkout(branch) as current_branch:
        previous_ff = FieldFinder.crawl(
            serializer_directory, view_directory, files=files
        )

    affected_serializers = current_ff.difference(previous_ff)

    if affected_serializers:
        print('From {} -> {}\n'.format(
            colored(branch, consts.Colours.INFO, attrs=['bold']),
            colored(current_branch, consts.Colours.INFO, attrs=['bold'])
        ))

        if affected_serializers.added:
            for serializer_name in affected_serializers.added:
                name_desc = colored('+ ' + serializer_name + '\n',
                                    consts.Colours.ADDED,
                                    attrs=['underline', 'bold'])
                fields_dict = (current_ff.find_serializer_fields(serializer_name)
                                         .as_dict())
                fields_pp = '\n'.join(
                    '++ ' + line
                    for line in pformat(fields_dict).split('\n')
                )
                fields_pp = colored(fields_pp, consts.Colours.ADDED)
                print(name_desc + fields_pp + '\n')

        if affected_serializers.removed:
            removed_pp = ['- ' + serializer_name
                          for serializer_name in affected_serializers.removed]
            cprint(removed_pp, consts.Colours.REMOVED)

    registry = current_ff.serializer_registry
    for filename in changed_files:
        for serializer_name in registry.get_classes_in_file(filename):
            # this case handled above
            if serializer_name in affected_serializers.added:
                continue

            current_fields = current_ff.find_serializer_fields(serializer_name)
            previous_fields = previous_ff.find_serializer_fields(serializer_name)

            diff = current_fields.stringify_diff(previous_fields)

            if diff:
                name_desc = colored(serializer_name,
                                    consts.Colours.ADDED,
                                    attrs=['underline', 'bold'])
                print(name_desc)
                print(diff)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--branch', help='Previous branch name',
                        default='master')
    parser.add_argument('--root', help='Project root (sigma)')

    args = parser.parse_args()

    main(args.branch, args.root)
