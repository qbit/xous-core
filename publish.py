#! /usr/bin/env python3
import argparse
from pathlib import Path
import re
import subprocess
import time

# format is {crate : path}
CRATES = {
    "xous" : "xous-rs",
    "xous-kernel" : "kernel",
    "xous-ipc" : "xous-ipc",
    "xous-api-log" : "api/xous-api-log",
    "xous-api-names" : "api/xous-api-names",
    "xous-api-susres" : "api/xous-api-susres",
    "xous-api-ticktimer" : "api/xous-api-ticktimer",
    "xous-log" : "services/xous-log",
    "xous-names" : "services/xous-names",
    "xous-susres" : "services/xous-susres",
    "xous-ticktimer" : "services/xous-ticktimer",
}
UTRA_CRATES = {
    "svd2utra" : "svd2utra",
    "utralib" : "utralib",
}
VERSIONS = {}

class PatchInfo:
    def __init__(self, filename, cratelist=None, cratename=None):
        self.filepath = Path(filename)
        if not self.filepath.is_file():
            print("Bad crate path: {}".format(filename))
        self.cratename = cratename
        self.cratelist = cratelist

    def get_version(self):
        with open(self.filepath, 'r') as file:
            lines = file.readlines()
            in_package = False
            name_check = False
            for line in lines:
                if line.strip().startswith('['):
                    if 'package' in line:
                        in_package = True
                    else:
                        in_package = False
                    continue
                elif in_package:
                    if line.strip().startswith('version'):
                        version = line.split('=')[1].replace('"', '').strip()
                    if line.strip().startswith('name'):
                        name = line.split('=')[1].replace('"', '').strip()
                        if name in self.cratelist:
                            name_check = True
            if name_check:
                assert version is not None # "Target name found but no version was extracted!"
                VERSIONS[name] = version

            return name_check

    # assumes that VERSIONS has been initialized.
    def increment_versions(self):
        # check that global variables are in sane states
        assert len(VERSIONS) > 0 # "No VERSIONS found, something is weird."
        with open(self.filepath, 'r') as file:
            lines = file.readlines()
        with open(self.filepath, 'w') as file:
            in_package = False
            in_dependencies = False
            for line in lines:
                if line.strip().startswith('['):
                    if 'package' in line:
                        in_package = True
                    else:
                        in_package = False
                    if 'dependencies' in line:
                        in_dependencies = True
                    else:
                        in_dependencies = False
                    file.write(line)
                elif line.strip().startswith('#'): # skip comments
                    file.write(line)
                elif in_package:
                    # increment my own version, if I'm in the listed crates
                    if self.cratename is not None:
                        if line.strip().startswith('version'):
                            file.write('version = "{}"\n'.format(bump_version(VERSIONS[self.cratename])))
                        else:
                            file.write(line)
                    else:
                        file.write(line)

                    if line.strip().startswith('name'):
                        this_crate = line.split('=')[1].replace('"', '').strip()
                        print("Patching {}...".format(this_crate))
                elif in_dependencies:
                    # now increment dependency versions

                    # first search and see if the dependency name is in the table
                    if 'package' in line: # renamed package
                        semiparse = re.split('=|,', line.strip())
                        if 'package' in semiparse[0]:
                            # catch the case that the crate name has the word package in it. If this error gets printed,
                            # we have to rewrite this semi-parser to be smarter about looking inside the curly braces only,
                            # instead of just stupidly splitting on = and ,
                            print("Warning: crate name has the word 'package' in it, and we don't parse this correctly!")
                            print("Searching in {}, found {}".format(this_crate, semiparse[0]))
                        else:
                            # extract the first index where 'package' is found
                            index = [idx for idx, s in enumerate(semiparse) if 'package' in s][0]
                            depcrate = semiparse[index + 1].replace('"', '').strip()
                            # print("assigned package name: {}".format(depcrate))
                    else: # simple version number
                        depcrate = line.strip().split('=')[0].strip()
                        # print("simple package name: {}".format(depcrate))

                    # print("{}:{}".format(this_crate, depcrate))
                    if depcrate in VERSIONS:
                        oldver = VERSIONS[depcrate]
                        (newline, numsubs) = re.subn(oldver, bump_version(oldver), line)
                        if numsubs != 1 and not "\"*\"" in newline:
                            print("Warning! Version substitution failed for {}:{} in crate {} ({})".format(depcrate, oldver, this_crate, numsubs))

                        # print("orig: {}\nnew: {}".format(line, newline))
                        file.write(newline)
                    else:
                        file.write(line)
                else:
                    file.write(line)

def bump_version(semver):
    components = semver.split('.')
    components[-1] = str(int(components[-1]) + 1)
    retver = ""
    for (index, component) in enumerate(components):
        retver += str(component)
        if index < len(components) - 1:
            retver += "."
    return retver

def merge_two_dicts(x, y):
    z = x.copy()
    z.update(y)
    return z

def main():
    parser = argparse.ArgumentParser(description="Update and publish crates")
    parser.add_argument(
        "-x", "--xous", help="Process Xous kernel dependent crates", action="store_true",
    )
    parser.add_argument(
        "-u", "--utralib", help="Process UTRA dependent crates", action="store_true",
    )
    parser.add_argument(
        "-b", "--bump", help="Do a version bump", action="store_true",
    )
    parser.add_argument(
        "-p", "--publish", help="Publish crates", action="store_true",
    )
    parser.add_argument(
        "-w", "--wet-run", help="Used in conjunction with --publish to do a 'wet run'", action="store_true"
    )
    args = parser.parse_args()

    if not(args.xous or args.utralib):
        print("Warning: no dependencies selected, operation is a no-op. Use -x/-u/... to select dependency trees")
        exit(1)

    cratelist = {}
    if args.xous:
        cratelist = merge_two_dicts(cratelist, CRATES)
    if args.utralib:
        cratelist = merge_two_dicts(cratelist, UTRA_CRATES)
        if not args.xous: # most Xous crates are also affected by this, so they need a bump as well
            cratelist = merge_two_dicts(cratelist, CRATES)

    if args.bump:
        cargo_toml_paths = []
        for path in Path('.').rglob('Cargo.toml'):
            if 'target' not in str(path):
                not_core_path = True
                for editpath in cratelist.values():
                    if editpath in str(Path(path)).replace('\\', '/'): # fix windows paths
                        not_core_path = False
                if not_core_path:
                    cargo_toml_paths += [path]

        # import pprint
        # pp = pprint.PrettyPrinter(indent=2)
        # pp.pprint(cargo_toml_paths)

        patches = []
        # extract the versions of crates to patch
        for (crate, path) in cratelist.items():
            #print("extracting {}".format(path))
            patchinfo = PatchInfo(path + '/Cargo.toml', cratelist, crate)
            if not patchinfo.get_version():
                print("Couldn't extract version info from {} crate".format(crate))
                exit(1)
            patches += [patchinfo]

        # now extract all the *other* crates
        for path in cargo_toml_paths:
            #print("{}".format(str(path)))
            patchinfo = PatchInfo(path)
            patches += [patchinfo]

        print(VERSIONS)
        for (name, ver) in VERSIONS.items():
            print("{}: {} -> {}".format(name, ver, bump_version(ver)))

        for patch in patches:
            patch.increment_versions()

    if args.publish:
        # small quirk: if you're doing a utralib update, just use -u only.
        # there is some order-sensitivity in how the dictionaries are accessed
        # but of course dictionaries are unordered. I think we need to re-do
        # the specifier from a dictionary to an ordered list, to gurantee that
        # publishing happens in the correct operation order.
        wet_cmd = ["cargo",  "publish"]
        dry_cmd = ["cargo",  "publish", "--dry-run", "--allow-dirty"]
        if args.wet_run:
            cmd = wet_cmd
        else:
            cmd = dry_cmd
        for (crate, path) in cratelist.items():
            print("Publishing {} in {}".format(crate, path))
            try:
                subprocess.run(cmd, cwd=path, check=True)
            except subprocess.CalledProcessError:
                print("Process failed, waiting for crates.io to update and retrying...")
                time.sleep(10)
                # just try running it again
                try:
                    subprocess.run(cmd, cwd=path, check=True)
                except:
                    print("Retry failed, moving on anyways...")
            time.sleep(10)

if __name__ == "__main__":
    main()
    exit(0)