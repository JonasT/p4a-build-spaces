'''
Copyright (c) 2018-2019 p4a-build-spaces team and others, see AUTHORS.md

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''

import argparse
import subprocess
import sys

from p4aspaces.actions import actions
import p4aspaces.buildenv as buildenv

def process_uname_arg(arg, complain_about_root=True):
    uname_or_id = arg
    try:
        uname_or_id = int(arg)
    except (TypeError, ValueError):
        pass

    # Try treating as user id:
    try:
        uidresult = int(uname_or_id)
        # If this worked, take it as user id and be done.
        return uidresult
    except (TypeError, ValueError):
        pass

    # Try treating as user:
    if uname_or_id != "interactive_prompt":
        try:
            import pwd
            uidresult = pwd.getpwnam(uname_or_id).pw_uid
            return uidresult
        except KeyError:
            print("COULDN'T RESOLVE USER ID: " + str(uname_or_id))

    if complain_about_root:
        while True:
            print("Please specify a user on your host to "+
                "use for permissions (to avoid running " +
                "the build as root, which is UNSAFE).")
            print("Use --map-to-user option to skip this prompt next time.")
            unameresult = input("Username:")
            if (unameresult == "root" or str(unameresult) == "0") and \
                    complain_about_root:
                result = input("You specified 'root'. This is UNSAFE. " +
                    "Continue? [y/N]")
                if not result.lower() in ["y", "j", "yes"]:
                    continue
                uname_or_id = 0
                return uname_or_id
            if len(unameresult.strip()) == 0:
                continue
            return process_uname_arg(unameresult)
    else:
        return "1"

def launch_shell_or_cmd(args, shell=False):
    if shell:
        argparser = argparse.ArgumentParser(
            description="action \"shell\": " +
            str(actions()["shell"]["description"]))
    else:
        argparser = argparse.ArgumentParser(
            description="action \"cmd\": " +
            str(actions()["cmd"]["description"]))
    argparser.add_argument("env",
        default=None, nargs=1,
        help="Specify an environment to use. Use 'p4aspaces list-envs' " +
        "to list available environments")
    argparser.add_argument("--map-to-user",
        default="interactive_prompt", nargs=1,\
        help="The unprivileged user which to run as. If you use a " +
        "workspace (with --workspace), specify the user here that " +
        "owns the workspace so you can run the build as non-root " +
        "while still having correct access permissions",
        dest="maptouser")
    argparser.add_argument("--force-redownload-p4a",
        default=False, action="store_true",
        help="Force docker to rebuild from the p4a download step " +
        "(previous step remain cached), to ensure the newest version " +
        "as present in the repo", dest="force_p4a_redownload")
    argparser.add_argument("--force-rebuild",
        default=False, action="store_true",
        help="Force docker to rebuild entire image from scratch, " +
        "without using any caching", dest="clean_image_rebuild")
    argparser.add_argument("--workspace",
        help="Specify a workspace directory to be mounted into the " +
        "build environment at ~/workspace. If not specified, there " +
        "will be no access to files outside of the container",
        default=None, dest="workspace", nargs="?")
    if not shell:
        argparser.add_argument("command", nargs=1,
            help="The command to run, defaults to 'bash'. If you want to " +
            "just build the demo app, replace with 'testbuild' (which will " +
            "automatically write it's result to the --output target)",
            default="bash")
        argparser.add_argument("--output",
            help="Path where to place any .apk encountered after the " +
            "build inside the build environments internal ~/output folder",
            default=None, nargs="?",
            dest="output_file")
    argparser.add_argument("--p4a",
        default=None, nargs="?",
        help="Specify p4a release archive to use " +
        "(like 'https://github.com/kivy/python-for-android/" +
        "archive/master.zip'), or the branch " +
        "name (like 'master'). Will default to master branch " +
        "if unspecified", dest="p4a_url")
    argparser.add_argument("--buildozer",
        default=None, nargs="?",
        help="Specify buildozer release archive to use " +
        "(like 'https://github.com/kivy/buildozer/" +
        "archive/master.zip'), or the branch " +
        "name (like 'master'). Will default to stable on pypi " +
        "if unspecified", dest="buildozer_url")
    args = argparser.parse_args(args)
    if shell:
        args.command = "bash"
        args.output_file = None
    else:
        if len(args.command) > 0:
            args.command = args.command[0]
    if len(args.env) > 0:
        args.env = args.env[0]

    # List environments:
    envs = buildenv.get_environments()

    # Test docker availability:
    try:
        output = subprocess.check_output(["docker", "ps"],
            stderr=subprocess.STDOUT)
    except (subprocess.CalledProcessError,
            FileNotFoundError) as e:
        print("p4aspaces: error: `docker ps` test command failed. " +
            "\n       Is docker running, and do we have access?",
            file=sys.stderr, flush=True)
        sys.exit(1)

    # Choose user:
    if type(args.maptouser) == list:
        args.maptouser = args.maptouser[0]
    uname_or_id = process_uname_arg(args.maptouser)

    # Choose environment:
    env_name = args.env
    if len([env for env in envs if env.name == env_name]) == 0:
        print("p4aspaces: error: Not a known environment. Aborting.",
              file=sys.stderr, flush=True)
        sys.exit(1)
    env = [env for env in envs if env.name == env_name][0]

    # Choose download target:
    dl_target_p4a = "master"
    dl_target_buildozer = "stable"
    if args.p4a_url is not None:
        dl_target_p4a = args.p4a_url
    if args.buildozer_url is not None:
        dl_target_buildozer = args.buildozer_url

    # Launch it:
    env.p4a_target = dl_target_p4a
    env.buildozer_target = dl_target_buildozer
    env.launch_shell(
        force_p4a_refetch=args.force_p4a_redownload,
        output_file=args.output_file,
        launch_cmd=args.command,
        workspace=args.workspace,
        user_id_or_name=uname_or_id,
        clean_image_rebuild=args.clean_image_rebuild)

