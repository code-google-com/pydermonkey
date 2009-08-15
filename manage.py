#! /usr/bin/env python

import os
import sys

if __name__ == '__main__':
    # This code is run if we're executed directly from the command-line.

    myfile = os.path.abspath(__file__)
    mydir = os.path.dirname(myfile)
    sys.path.insert(0, os.path.join(mydir, 'python-modules'))

    args = sys.argv[1:]
    if not args:
        args = ['help']

    # Have paver run this very file as its pavement script.
    args = ['-f', myfile] + args

    import paver.tasks
    paver.tasks.main(args)
    sys.exit(0)

# This code is run if we're executed as a pavement script by paver.

import os
import subprocess
import shutil
import sys
import webbrowser
import urllib

from paver.easy import *

@task
def docs(options):
    """Open the Pymonkey documentation in your web browser."""

    url = os.path.abspath(os.path.join("docs", "rendered", "index.html"))
    url = urllib.pathname2url(url)
    webbrowser.open(url)

@task
def build_docs(options):
    """Build the Pymonkey documentation (requires Sphinx)."""

    retval = subprocess.call(["sphinx-build",
                              "-b", "html",
                              os.path.join("docs", "src"),
                              os.path.join("docs", "rendered")])
    if retval:
        sys.exit(retval)

@task
@cmdopts([("objdir=", "o", "The root of your Mozilla objdir"),
          ("static", "s", "Build against static libraries")])
def build(options):
    """Build the Pymonkey Python C extension."""

    objdir = options.get("objdir")
    if not objdir:
        print("Objdir not specified! Please specify one with "
              "the --objdir option.")
        sys.exit(1)
    objdir = os.path.abspath(objdir)
    incdir = os.path.join(objdir, "dist", "include")
    libdir = os.path.join(objdir, "dist", "lib")

    print "Building extension."

    args = ["g++",
            "-framework", "Python",
            "-I%s" % incdir,
            "-L%s" % libdir,
            "-Wall",
            "-o", "pymonkey.so",
            "-dynamiclib",
            "pymonkey.cpp",
            "utils.cpp",
            "object.cpp",
            "function.cpp",
            "undefined.cpp",
            "context.cpp",
            "runtime.cpp"]

    if options.get("static"):
        args.append(os.path.join(objdir, "libjs_static.a"))
    else:
        args.append("-lmozjs")

    result = subprocess.call(args)

    if result:
        sys.exit(result)

    print "Running test suite."

    new_env = {}
    new_env.update(os.environ)
    if not options.get("static"):
        print("NOTE: Because you're linking dynamically to the "
              "SpiderMonkey shared library, you'll need to make sure "
              "that it's on your library load path. You may need to "
              "add %s to your library load path to do this." %
              libdir)
        new_env['DYLD_LIBRARY_PATH'] = libdir

    result = subprocess.call(
        [sys.executable,
         "test_pymonkey.py"],
        env = new_env
        )

    if result:
        sys.exit(result)

    print "Running doctests."

    # We have to add our current directory to the python path so that
    # our doctests can find the pymonkey module.
    new_env['PYTHONPATH'] = os.path.abspath('.')
    retval = subprocess.call(["sphinx-build",
                              "-b", "doctest",
                              os.path.join("docs", "src"),
                              "_doctest_output"],
                             env = new_env)
    if retval:
        sys.exit(retval)
