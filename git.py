import re

from contextlib import contextmanager
from subprocess import Popen, PIPE

import consts


def checked_command(args, ignore_if=''):
    # TODO: ghetto function..
    process = Popen(args, stderr=PIPE, stdout=PIPE)
    err = process.stderr.read()
    if err and not err.startswith(ignore_if):
        raise Exception(err)

    return process


def get_current_branch():
    process = checked_command(["git", "status"])
    r = re.match(r'On branch (.*)', process.stdout.readline())
    return r.groups()[0]


@contextmanager
def git_checkout(branch):
    current_branch = get_current_branch()
    checked_command(["git", "checkout", branch], ignore_if='Switched')
    yield current_branch
    checked_command(["git", "checkout", current_branch], ignore_if='Switched')


def get_my_ip():
    p = Popen(['dig', '+short', 'myip.opendns.com', '@resolver1.opendns.com'],
              stdout=PIPE)
    return p.stdout.read().strip()


def get_changed_files(branch='master'):
    # TODO: this is ghetto...
    if get_my_ip() != consts.OFFICE_IP:
        raise Exception('Not on VPN')

    with git_checkout(branch):
        checked_command(["git", "pull"], ignore_if='From')

    process = checked_command(["git", "diff", "--name-only", branch, "apiv2/serializers"])

    return [re.sub('sigma/', './', x) for x in process.stdout.read().split()]


