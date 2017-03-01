from distutils.core import setup
from distutils.extension import Extension
from distutils.command.build_ext import build_ext
import os, os.path, stat, shutil, subprocess, re

# where an OpenSSL 1.0.1+ libssl.dylib and libcrypto.dylib are now
LIBS_SRC  = "/usr/local/opt/openssl/lib"
# where you'll want them eventually installed
LIBS_DEST = "/usr/local/lib/tlsssl"
# where the associated headers are
HEADER_SRC = "/usr/local/opt/openssl/include"

class custom_ext(build_ext):
    def run(self):
        if not self.dry_run:
            # Step 1: make sure the _ssl_data.h header has been generated
            ssl_data = os.path.join(os.path.dirname(__file__), "_ssl_data.h")
            if not os.path.isfile(ssl_data):
                tool_path = os.path.join(os.path.dirname(__file__), "make_tlsssl_data.py")
                # Run the generating script
                _ = subprocess.check_output(['/usr/bin/python', tool_path, HEADER_SRC, ssl_data])
            # Step 2: remove the temporary work directory under the build directory
            workspace_rel = os.path.join(self.build_temp, "../_temp_libs")
            workspace_abs = os.path.realpath(workspace_rel)
            shutil.rmtree(workspace_abs, ignore_errors=True)
            # Step 3: make the temporary work directory exist
            self.mkpath(workspace_rel)
            # Step 4: copy and rename the dylibs to there
            ssl_src    = os.path.join(LIBS_SRC, "libssl.dylib")
            crypt_src  = os.path.join(LIBS_SRC, "libcrypto.dylib")
            ssl_tmp    = os.path.join(workspace_abs, "libtlsssl.dylib")
            crypt_tmp  = os.path.join(workspace_abs, "libtlscrypto.dylib")
            shutil.copy(ssl_src, ssl_tmp)
            shutil.copy(crypt_src, crypt_tmp)
            # Step 5: change the ids of the dylibs
            ssl_dest   = os.path.join(LIBS_DEST, "libtlsssl.dylib")
            crypt_dest = os.path.join(LIBS_DEST, "libtlscrypto.dylib")
            # (need to temporarily mark them as writeable)
            st = os.stat(ssl_tmp)
            os.chmod(ssl_tmp, st.st_mode | stat.S_IWUSR)
            st = os.stat(crypt_tmp)
            os.chmod(crypt_tmp, st.st_mode | stat.S_IWUSR)
            _ = subprocess.check_output(['/usr/bin/install_name_tool', '-id', ssl_dest,   ssl_tmp])
            _ = subprocess.check_output(['/usr/bin/install_name_tool', '-id', crypt_dest, crypt_tmp])
            # Step 6: change the link between ssl and crypto
            # This part is a bit trickier - we need to take the existing entry for libcrypto on libssl
            # and remap it to the new location
            link_output = subprocess.check_output(['/usr/bin/otool', '-L', ssl_tmp])
            old_path = re.findall('^\t(/[^\(]+?libcrypto.*?.dylib)', link_output, re.MULTILINE)[0]
            _ = subprocess.check_output(['/usr/bin/install_name_tool', '-change', old_path, crypt_dest, ssl_tmp])
            # Step 7: cleanup permissions
            st = os.stat(ssl_tmp)
            os.chmod(ssl_tmp, st.st_mode & ~stat.S_IWUSR)
            st = os.stat(crypt_tmp)
            os.chmod(crypt_tmp, st.st_mode & ~stat.S_IWUSR)
            # Step 8: patch in the additional paths and linkages
            self.include_dirs.insert(0, HEADER_SRC)
            self.library_dirs.insert(0, workspace_abs)
            self.libraries.insert(0,"tlsssl")
        result = build_ext.run(self)
        # After we're done compiling, lets put the libs in with the build and clean up the temp directory
        if not self.dry_run:
            # Step 1: clear out stale dylibs that may be in the final build directory
            ssl_build   = os.path.join(self.build_lib, "libtlsssl.dylib")
            crypt_build = os.path.join(self.build_lib, "libtlscrypto.dylib")
            if os.path.isfile(ssl_build):
                os.remove(ssl_build)
            if os.path.isfile(crypt_build):
                os.remove(crypt_build)
            # Step 2: move the dylibs into the final build directory
            shutil.move(ssl_tmp, self.build_lib)
            shutil.move(crypt_tmp, self.build_lib)
            # Step 3: get rid of the temp lib directory
            shutil.rmtree(workspace_abs, ignore_errors=True)
        return result

# Prior to running setup, we should be making our patched files if they don't exist

def prep():
    patch_pairs = [
                   ['_tlsssl.c',           '_src/_ssl.c', ],
                   ['make_tlsssl_data.py', '_src/make_ssl_data.py'],
                   ['tlsssl.py',          '_src/ssl.py'],
                  ]
    for dest, source in patch_pairs:
        if not os.path.isfile(os.path.join(os.path.dirname(__file__), dest)):
            source = os.path.join(os.path.dirname(__file__), source)
            diff   = os.path.join(os.path.dirname(__file__), '_diffs', "%s.diff" % dest)
            dest   = os.path.join(os.path.dirname(__file__), dest)
            _ = subprocess.check_output(['/usr/bin/patch', source, diff, "-o", dest])
    # Copy over the socketmodule.h file as well
    if not os.path.isfile(os.path.join(os.path.dirname(__file__), "socketmodule.h")):
        source = os.path.join(os.path.dirname(__file__), "_src", "socketmodule.h")
        shutil.copy(source, os.path.realpath(os.path.join(os.path.dirname(__file__))))

prep()

setup(
    name='tlsssl',
    description='TLS support backported into the macOS system python',
    url='https://github.com/pudquick/tlsssl',
    py_modules=['tlsssl'],
    ext_modules=[Extension("_tlsssl", ["_tlsssl.c"],
        libraries = ["tlsssl"],
        )],
    cmdclass={'build_ext': custom_ext}
)
