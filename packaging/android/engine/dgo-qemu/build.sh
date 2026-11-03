# dgo-qemu — QEMU for the Digital Office's Android app (DGO-1071): a termux-packages recipe, copied into
# termux-packages/packages/dgo-qemu by .github/workflows/android-engine.yml, beside the bionic patches and
# the aarch64 setjmp of Termux's own qemu-system-x86-64-headless (same version, same source, same sha256).
# That version is the one at TERMUX_PACKAGES_COMMIT in android-engine.yml: bump the two together.
#
# Trimmed to what a server guest needs, because Termux's full recipe is not buildable from source in one
# runner: its libspice-server pulls GStreamer → mesa → all of LLVM (the second reader of 5d459659). Kept:
# the aarch64 system target, user-mode networking (slirp: no root, no TAP on a phone), qemu-img, KVM where
# a phone gives it. Dropped: every other target, user-mode emulation, audio, spice, USB, VNC, curses,
# TLS, ssh, curl and every image format but raw and qcow2.
TERMUX_PKG_HOMEPAGE=https://www.qemu.org
TERMUX_PKG_DESCRIPTION="QEMU's aarch64 system emulator, headless, for the Digital Office's engine"
TERMUX_PKG_LICENSE="GPL-2.0"
TERMUX_PKG_MAINTAINER="Bina Solutions"
TERMUX_PKG_VERSION="1:11.1.2"
TERMUX_PKG_SRCURL="https://download.qemu.org/qemu-${TERMUX_PKG_VERSION:2}.tar.xz"
TERMUX_PKG_SHA256=731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016
TERMUX_PKG_DEPENDS="dtc, glib, libandroid-shmem, libpixman, libslirp, resolv-conf, zlib, zstd"
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_pre_configure() {
	# Termux's workaround for https://github.com/termux/termux-packages/issues/12261, as in its recipe.
	rm -f $TERMUX_PKG_BUILDDIR/_lib
	mkdir -p $TERMUX_PKG_BUILDDIR/_lib
	cd $TERMUX_PKG_BUILDDIR
	mkdir -p _setjmp-aarch64
	pushd _setjmp-aarch64
	mkdir -p private
	local s
	for s in $TERMUX_PKG_BUILDER_DIR/setjmp-aarch64/{setjmp.S,private-*.h}; do
		local f=$(basename ${s})
		cp ${s} ./${f/-//}
	done
	$CC $CFLAGS $CPPFLAGS -I. setjmp.S -c
	$AR cru $TERMUX_PKG_BUILDDIR/_lib/libandroid-setjmp.a setjmp.o
	popd
	LDFLAGS+=" -L$TERMUX_PKG_BUILDDIR/_lib -l:libandroid-setjmp.a"
}

termux_step_configure() {
	termux_setup_ninja
	CFLAGS+=" $CPPFLAGS"
	CXXFLAGS+=" $CPPFLAGS"
	LDFLAGS+=" -landroid-shmem -llog"
	# --without-default-features, then only what the engine uses; stack protector flags come from the
	# build scripts (as in Termux's recipe)
	./configure \
		--prefix="$TERMUX_PREFIX" \
		--cross-prefix="${TERMUX_HOST_PLATFORM}-" \
		--host-cc="gcc" \
		--cc="$CC" \
		--cxx="$CXX" \
		--objcc="$CC" \
		--disable-stack-protector \
		--without-default-features \
		--disable-docs \
		--disable-werror \
		--disable-user \
		--enable-system \
		--enable-tools \
		--enable-slirp \
		--enable-fdt=system \
		--enable-zstd \
		--enable-pixman \
		--enable-kvm \
		--enable-coroutine-pool \
		--enable-trace-backends=nop \
		--audio-drv-list="" \
		--target-list="aarch64-softmmu"
}
