"""Fixture: a second HTTP client in disguise. Every `# expect:` line must be reported."""

import asyncio  # expect: sym-single-egress
import os
import subprocess


async def reach(host, loop):
    subprocess.run(["curl", "-s", host])  # expect: sym-network-subprocess
    subprocess.check_output("wget " + host, shell=True)  # expect: sym-network-subprocess sym-subprocess-literal-command
    subprocess.Popen(["/usr/bin/ssh", host])  # expect: sym-network-subprocess
    os.system("nc -z " + host + " 80")  # expect: sym-network-subprocess sym-subprocess-literal-command
    os.popen("scp a b")  # expect: sym-network-subprocess
    await asyncio.open_connection(host, 80)  # expect: sym-network-subprocess
    await loop.create_connection(object, host, 80)  # expect: sym-network-subprocess
    subprocess.run(["git", "status"])
    subprocess.run(["ssh-keygen", "-l"])
    os.system("ls -l")


def computed_commands(tool, host, args):
    subprocess.run(tool)  # expect: sym-subprocess-literal-command
    subprocess.run("echo " + host, shell=True)  # expect: sym-subprocess-literal-command
    subprocess.check_output(f"ls {host}", shell=True)  # expect: sym-subprocess-literal-command
    subprocess.Popen([tool, host])  # expect: sym-subprocess-literal-command
    subprocess.run(args, check=True)  # expect: sym-subprocess-literal-command
    os.system(tool)  # expect: sym-subprocess-literal-command
    os.popen("echo " + host)  # expect: sym-subprocess-literal-command
    subprocess.run(["git", host])
    subprocess.run("git status", shell=True)
    os.system("ls")
