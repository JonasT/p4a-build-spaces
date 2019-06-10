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

import os
from .settings import settings
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import urllib.parse

class BuildEnvironment(object):
    def __init__(self,
            folder_path,
            envs_base_dir,
            p4a_target="master",
            buildozer_target="stable"
            ):
        self.path = os.path.normpath(os.path.abspath(folder_path))
        if not os.path.exists(folder_path):
            raise RuntimeError("BuildEnvironment() needs " +
                "valid, existing base folder: " + str(folder_path))
        self.name = os.path.basename(self.path)
        self.envs_dir = envs_base_dir
        self.p4a_target = p4a_target
        self.buildozer_target = buildozer_target
        self.description = open(
            os.path.join(self.path, "short_description.txt"),
            "r",
            encoding="utf-8"
        ).read().strip().partition("\n")[0]

    def get_docker_file(self,
            force_p4a_refetch=False,
            launch_cmd="bash",
            start_dir="/home/userhome",
            add_workspace=False,
            user_id_or_name="root"):
        image_name = "p4atestenv-" + str(self.name)

        # Obtain p4a build uuid (to control docker caching):
        env_settings = settings.get("environments", type=dict)
        if not self.name in env_settings:
            env_settings[self.name] = dict()
        if not "last_build_p4a_uuid" in env_settings[self.name] or \
                force_p4a_refetch:
            build_p4a_uuid = str(uuid.uuid4())
        else:
            build_p4a_uuid = env_settings[self.name]["last_build_p4a_uuid"]
        env_settings[self.name]["last_build_p4a_uuid"] = build_p4a_uuid
        settings.set("environments", env_settings)

        dl_target_p4a = self.p4a_target
        dl_target_buildozer = self.buildozer_target
        def process_dl_target(package_name, dl_target, repo, default=None):
            if dl_target is None or len(dl_target_p4a.strip()) == 0:
                dl_target = default
            elif dl_target == "stable":
                dl_target = package_name
            elif dl_target.find("/") < 0 and \
                    dl_target.find("\\") < 0:  # probably a branch
                dl_target = repo + "/" +\
                    "archive/" + urllib.parse.quote(dl_target) + ".zip"
            else:
                dl_target = str(dl_target).strip()
            return dl_target
        dl_target_p4a = process_dl_target(
            "python-for-android", dl_target_p4a,
            "https://github.com/kivy/python-for-android",
            default=("https://github.com/kivy/python-for-android/"
                     "archive/master.zip"))
        dl_target_buildozer = process_dl_target(
            "buildozer", dl_target_buildozer,
            "https://github.com/kivy/buildozer",
            default="buildozer")

        with open(os.path.join(self.envs_dir, "setup_user_env.txt"),
                  "r") as f:
            setup_user_env_instructions = f.read().strip()
        with open(os.path.join(self.envs_dir, "install_shared_packages.txt"),
                  "r") as f:
            install_shared_instructions = f.read().strip()
        with open(os.path.join(self.envs_dir, "install_shared_packages_user.txt"),
                  "r") as f:
            install_shared_instructions_user = f.read().strip()
        with open(os.path.join(self.path, "Dockerfile"), "r") as f:
            t = f.read()
            install_shared_instructions_user = \
                install_shared_instructions_user.replace(
                "{P4A_URL}", "'" + str(
                dl_target_p4a.replace("'", "'\"'\"'")) + "'").replace(
                "{P4A_COMMENT}", " # " +
                "p4a build " + str(build_p4a_uuid)).replace(
                "{BUILDOZER_URL}", "'" + str(
                dl_target_buildozer.replace("'", "'\"'\"'")) + "'"
                )
            setup_user_env_instructions = \
                setup_user_env_instructions.replace(
                "{INSTALL_SHARED_PACKAGES_USER}",
                install_shared_instructions_user)
            t = t.replace(
                "{SETUP_USER_ENV}", setup_user_env_instructions).replace(
                "{INSTALL_SHARED_PACKAGES}", install_shared_instructions)
            t = t.replace(
                "{LAUNCH_CMD}",
                launch_cmd.replace("\\", "\\\\").\
                    replace("\n", "\\n").\
                    replace("\r", "\\r").replace("'", "'\"'\"'"))
            if user_id_or_name == "root" or str(user_id_or_name) == "0":
                t = t.replace("{PREPARE_USER}", "ENV HOME /home/userhome\n" +
                    "ENV BUILDUSERNAME root")
                t = t.replace("{DROP_TO_USER}", "")
            else:
                uid = 1000
                uname = "builduser"
                try:
                    uid = int(user_id_or_name)
                except (TypeError, ValueError):
                    uid = 1000
                    uname = user_id_or_name
                t = t.replace("{PREPARE_USER}",
                    "RUN useradd -b /home -d /home/userhome/ -u " +
                        str(uid) + " " + str(uname) + "\n" +
                    "RUN chown -R " + str(uname) + " /home/userhome\n" +
                    "ENV BUILDUSERNAME " + str(uname) + "\n" +
                    "ENV HOME " + "/home/userhome")
                t = t.replace("{DROP_TO_USER}",
                    "USER " + str(uname))

            t = t.replace(
                "{START_DIR}", start_dir).replace(
                "{WORKSPACE_VOLUME}", "" if not add_workspace else \
                    "VOLUME /home/userhome/workspace/")
            return t

    def launch_shell(self,
            force_p4a_refetch=False,
            launch_cmd="bash",
            output_file=None,
            workspace=None,
            clean_image_rebuild=False,
            user_id_or_name="root",
            ccache_dir=os.path.join(tempfile.gettempdir(), "p4a-ccache")
            ):
        # Build container:
        image_name = "p4atestenv-" + str(self.name)
        container_name = image_name + "-" +\
            str(uuid.uuid4()).replace("-", "")
        temp_d = tempfile.mkdtemp(prefix="p4a-testing-space-")
        try:
            os.mkdir(os.path.join(temp_d, "output"))
            with open(os.path.join(temp_d, "Dockerfile"), "w") as f:
                f.write(self.get_docker_file(
                    force_p4a_refetch=force_p4a_refetch,
                    launch_cmd=launch_cmd,
                    user_id_or_name=user_id_or_name,
                    start_dir=("/home/userhome/" if workspace is None else \
                                        "/home/userhome/workspace/"),
                    add_workspace=(workspace is not None),
                ))
            
            # Build container:
            no_cache_opts = []
            if clean_image_rebuild:
                no_cache_opts.append("--no-cache")
            cmd = ["docker", "build"] + no_cache_opts + [
                "-t", image_name, "--file", os.path.join(
                temp_d, "Dockerfile"), "."]
            if subprocess.call(cmd, cwd=temp_d) != 0:
                print("p4spaces: error: build failed.",
                    file=sys.stderr)
                sys.exit(1)

            # Ensure output directory is writable:
            os.system("chmod 777 '" +
                os.path.join(temp_d, "output").replace("'", "'\"'\"'")
                + "'")

            # Ensure ccache directory exists & is writable:
            os.makedirs(shlex.quote(ccache_dir), exist_ok=True)
            os.makedirs(shlex.quote(
                os.path.join(ccache_dir, "contents")), exist_ok=True)
            os.makedirs(shlex.quote(
                os.path.join(ccache_dir, "pip-build-dir")), exist_ok=True)
            try:
                uid = int(user_id_or_name)
            except (TypeError, ValueError):
                uid = 1000
            os.system("chown -R " + str(uid) + " -- " + shlex.quote(ccache_dir))
            os.system("chmod a-rx -- " + shlex.quote(ccache_dir))
            os.system("chmod u+rx -- " + shlex.quote(ccache_dir))

            # Launch shell:
            workspace_volume_args = []
            if workspace != None:
                workspace_volume_args += ["-v",
                    os.path.abspath(workspace) +
                    ":/home/userhome/workspace:rw,Z"]
            cmd = ["docker", "run",
                "--name", container_name, "-ti",
                "-v", os.path.join(temp_d, "output") +
                ":/home/userhome/output:rw,Z",
                "-v", ccache_dir + ":/ccache/:rw,Z"] +\
                workspace_volume_args + [
                image_name
            ]
            subprocess.call(cmd)
            if output_file is not None:
                for f in os.listdir(os.path.join(temp_d, "output")):
                    full_path = os.path.join(temp_d, "output", f)
                    if not os.path.isdir(full_path) and f.endswith(".apk"):
                        shutil.copyfile(full_path, output_file)
                        return
        finally:
            try:
                os.system(
                    "docker kill " + container_name +
                    " > /dev/null 2>&1")
                print("Removing container...")
                os.system("docker rm " + container_name)
            finally:
                shutil.rmtree(temp_d)

def get_environments(for_p4a_target="master"):
    envs_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "environments"))
    env_names = [p for p in os.listdir(envs_dir) if (
        os.path.isdir(os.path.join(envs_dir, p)) and
        os.path.exists(os.path.join(envs_dir, p,
                                    "short_description.txt")) and
        not p.startswith("."))]
    result = [BuildEnvironment(os.path.join(envs_dir, env_name),
                               envs_dir,
                               p4a_target=for_p4a_target) \
              for env_name in sorted(env_names)]
    return result
