#!/usr/bin/env python3
import argparse
import fnmatch
import os
import shutil
import subprocess
import sys

from pathlib import Path


# Manifest inclusions
FIRMWARE_FILES = {
  "body/board/obj/body.bin.signed",
  "body/board/obj/bootstub.body.bin",
  "panda/board/obj/bootstub.panda.bin",
  "panda/board/obj/bootstub.panda_h7.bin",
  "panda/board/obj/panda.bin.signed",
  "panda/board/obj/panda_h7.bin.signed",
}

GENERATED_FILES = FIRMWARE_FILES | {
  "cereal/libcereal_shared.so",
  "cereal/messaging/bridge",
  "common/params_pyx.so",
  "common/transformations/transformations.so",
  "frogpilot/tinygrad_modeld/models/commonmodel_pyx.so",
  "frogpilot/tinygrad_modeld/models/driving_policy_metadata.pkl",
  "frogpilot/tinygrad_modeld/models/driving_policy_tinygrad.pkl",
  "frogpilot/tinygrad_modeld/models/driving_vision_metadata.pkl",
  "frogpilot/tinygrad_modeld/models/driving_vision_tinygrad.pkl",
  "msgq_repo/msgq/ipc_pyx.so",
  "msgq_repo/msgq/visionipc/visionipc_pyx.so",
  "opendbc/can/libdbc.so",
  "opendbc/can/packer_pyx.so",
  "opendbc/can/parser_pyx.so",
  "rednose_repo/rednose/helpers/ekf_sym_pyx.so",
  "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
  "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/libacados_ocp_solver_long.so",
  "selfdrive/locationd/locationd",
  "selfdrive/locationd/models/generated/libcar.so",
  "selfdrive/locationd/models/generated/liblive.so",
  "selfdrive/navd/libmaprender.so",
  "selfdrive/navd/mapsd",
  "selfdrive/pandad/pandad",
  "selfdrive/pandad/pandad_api_impl.so",
  "selfdrive/ui/_spinner",
  "selfdrive/ui/_text",
  "selfdrive/ui/qt/libpython_helpers.so",
  "selfdrive/ui/ui",
  "system/camerad/camerad",
  "system/logcatd/logcatd",
  "system/loggerd/bootlog",
  "system/loggerd/encoderd",
  "system/loggerd/loggerd",
  "system/proclogd/proclogd",
  "system/sensord/sensord",
  "system/ubloxd/ubloxd",
}

GENERATED_GLOBS = (
  "frogpilot/tinygrad_modeld/models/big_driving_*_metadata.pkl",
  "frogpilot/tinygrad_modeld/models/big_driving_*_tinygrad.pkl",
)

LEGAL_FILES = {
  "LICENSE",
  "body/LICENSE",
  "frogpilot/system/the_pond/assets/images/about.txt",
  "opendbc/LICENSE",
  "panda/LICENSE",
  "rednose_repo/LICENSE",
  "teleoprtc_repo/LICENSE",
  "third_party/libyuv/LICENSE",
  "tinygrad_repo/LICENSE",
}

REPOSITORY_WORKFLOWS = {
  ".github/workflows/compile_frogpilot.yaml",
  ".github/workflows/review_pull_request.yaml",
  ".github/workflows/schedule_update.yaml",
  ".github/workflows/update_pr_branch.yaml",
  ".github/workflows/update_release_branch.yaml",
}

CAMERAD_OPENCL_PROGRAM = "system/camerad/cameras/process_raw.cl"

CAMERAD_OPENCL_HEADERS = {
  "system/camerad/sensors/ar0231_cl.h",
  "system/camerad/sensors/os04c10_cl.h",
  "system/camerad/sensors/ox03c10_cl.h",
}

REQUIRED_FILES = GENERATED_FILES | LEGAL_FILES | REPOSITORY_WORKFLOWS | {
  "RELEASES.md",
  "common/version.h",
  "frogpilot/assets/city_lookup.sqlite",
  "frogpilot/classic_modeld/classic_modeld",
  "frogpilot/classic_modeld/models/navmodel_q.dlc",
  "frogpilot/classic_modeld/models/supercombo.thneed",
  "frogpilot/classic_modeld/transforms/loadyuv.cl",
  "frogpilot/classic_modeld/transforms/transform.cl",
  "frogpilot/navigation/mapd",
  "frogpilot/tinygrad_modeld/transforms/loadyuv.cl",
  "frogpilot/tinygrad_modeld/transforms/transform.cl",
  "launch_chffrplus.sh",
  "launch_env.sh",
  "launch_openpilot.sh",
  "panda/board/jungle/__init__.py",
  "selfdrive/assets/offroad/fcc.html",
  "selfdrive/assets/offroad/tc.html",
  "selfdrive/car/torque_data/override.toml",
  "selfdrive/car/torque_data/params.toml",
  "selfdrive/car/torque_data/substitute.toml",
  "selfdrive/modeld/modeld",
  "selfdrive/modeld/models/dmonitoring_model_q.dlc",
  "selfdrive/modeld/models/supercombo.thneed",
  "selfdrive/modeld/transforms/loadyuv.cl",
  "selfdrive/modeld/transforms/transform.cl",
  "selfdrive/navd/style.json",
  "selfdrive/ui/qt/offroad/text_view.qml",
  "selfdrive/ui/spinner",
  "selfdrive/ui/text",
  "system/camerad/cameras/process_raw.cl",
  "system/hardware/tici/agnos.json",
  "system/hardware/tici/updater",
}

RUNTIME_SUFFIXES = {
  ".capnp",
  ".cl",
  ".css",
  ".db",
  ".dbc",
  ".dlc",
  ".gif",
  ".gz",
  ".html",
  ".ico",
  ".jpeg",
  ".jpg",
  ".js",
  ".json",
  ".mjs",
  ".nmconnection",
  ".npy",
  ".pem",
  ".pkl",
  ".png",
  ".py",
  ".qml",
  ".signed",
  ".so",
  ".sqlite",
  ".svg",
  ".thneed",
  ".ttf",
  ".wav",
  ".woff",
  ".woff2",
}

SIGNAL_MARKER_GLOB = "frogpilot/assets/holiday_themes/*/signals/traditional_100"

SOURCE_SYMLINKS = {
  "frogpilot/assets/stock_theme/icons": "../../../selfdrive/assets/images",
  "frogpilot/assets/stock_theme/sounds": "../../../selfdrive/assets/sounds",
  "frogpilot/assets/stock_theme/steering_wheel/wheel.png": "../../../../selfdrive/assets/img_chffr_wheel.png",
  "msgq": "msgq_repo/msgq",
  "openpilot/common": "../common",
  "openpilot/frogpilot": "../frogpilot",
  "openpilot/selfdrive": "../selfdrive/",
  "openpilot/system": "../system/",
  "openpilot/third_party": "../third_party",
  "openpilot/tools": "../tools",
  "rednose": "rednose_repo/rednose",
  "teleoprtc": "teleoprtc_repo/teleoprtc",
  "third_party/acados/larch64/lib/libqpOASES_e.so": "libqpOASES_e.so.3.1",
  "third_party/snpe/larch64": "aarch64-ubuntu-gcc7.5",
  "tinygrad": "tinygrad_repo/tinygrad",
}

TOOLS_FILES = {
  "tools/lib/__init__.py",
  "tools/lib/api.py",
  "tools/lib/auth_config.py",
  "tools/lib/helpers.py",
  "tools/lib/route.py",
}

TINYGRAD_FILES = {
  "tinygrad_repo/LICENSE",
  "tinygrad_repo/tinygrad/__init__.py",
  "tinygrad_repo/tinygrad/codegen/__init__.py",
  "tinygrad_repo/tinygrad/codegen/gpudims.py",
  "tinygrad_repo/tinygrad/codegen/late/devectorizer.py",
  "tinygrad_repo/tinygrad/codegen/late/expander.py",
  "tinygrad_repo/tinygrad/codegen/late/linearize.py",
  "tinygrad_repo/tinygrad/codegen/lowerer.py",
  "tinygrad_repo/tinygrad/codegen/opt/__init__.py",
  "tinygrad_repo/tinygrad/codegen/opt/heuristic.py",
  "tinygrad_repo/tinygrad/codegen/opt/kernel.py",
  "tinygrad_repo/tinygrad/codegen/opt/postrange.py",
  "tinygrad_repo/tinygrad/codegen/opt/swizzler.py",
  "tinygrad_repo/tinygrad/codegen/opt/tc.py",
  "tinygrad_repo/tinygrad/codegen/quantize.py",
  "tinygrad_repo/tinygrad/device.py",
  "tinygrad_repo/tinygrad/dtype.py",
  "tinygrad_repo/tinygrad/engine/__init__.py",
  "tinygrad_repo/tinygrad/engine/jit.py",
  "tinygrad_repo/tinygrad/engine/memory.py",
  "tinygrad_repo/tinygrad/engine/realize.py",
  "tinygrad_repo/tinygrad/engine/schedule.py",
  "tinygrad_repo/tinygrad/gradient.py",
  "tinygrad_repo/tinygrad/helpers.py",
  "tinygrad_repo/tinygrad/nn/__init__.py",
  "tinygrad_repo/tinygrad/nn/datasets.py",
  "tinygrad_repo/tinygrad/nn/optim.py",
  "tinygrad_repo/tinygrad/nn/state.py",
  "tinygrad_repo/tinygrad/renderer/__init__.py",
  "tinygrad_repo/tinygrad/renderer/cstyle.py",
  "tinygrad_repo/tinygrad/renderer/llvmir.py",
  "tinygrad_repo/tinygrad/runtime/__init__.py",
  "tinygrad_repo/tinygrad/runtime/autogen/adreno.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/am.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/pm4_nv.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/pm4_soc15.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/sdma_4_0_0.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/sdma_4_4_2.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/sdma_5_0_0.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/sdma_6_0_0.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/smu_v13_0_0.py",
  "tinygrad_repo/tinygrad/runtime/autogen/am/smu_v14_0_2.py",
  "tinygrad_repo/tinygrad/runtime/autogen/comgr.py",
  "tinygrad_repo/tinygrad/runtime/autogen/comgr_3.py",
  "tinygrad_repo/tinygrad/runtime/autogen/hsa.py",
  "tinygrad_repo/tinygrad/runtime/autogen/kfd.py",
  "tinygrad_repo/tinygrad/runtime/autogen/kgsl.py",
  "tinygrad_repo/tinygrad/runtime/autogen/libc.py",
  "tinygrad_repo/tinygrad/runtime/autogen/libusb.py",
  "tinygrad_repo/tinygrad/runtime/autogen/llvm.py",
  "tinygrad_repo/tinygrad/runtime/autogen/opencl.py",
  "tinygrad_repo/tinygrad/runtime/autogen/pci.py",
  "tinygrad_repo/tinygrad/runtime/autogen/sqtt.py",
  "tinygrad_repo/tinygrad/runtime/autogen/vfio.py",
  "tinygrad_repo/tinygrad/runtime/graph/__init__.py",
  "tinygrad_repo/tinygrad/runtime/graph/hcq.py",
  "tinygrad_repo/tinygrad/runtime/ops_amd.py",
  "tinygrad_repo/tinygrad/runtime/ops_cpu.py",
  "tinygrad_repo/tinygrad/runtime/ops_gpu.py",
  "tinygrad_repo/tinygrad/runtime/ops_llvm.py",
  "tinygrad_repo/tinygrad/runtime/ops_npy.py",
  "tinygrad_repo/tinygrad/runtime/ops_qcom.py",
  "tinygrad_repo/tinygrad/runtime/support/__init__.py",
  "tinygrad_repo/tinygrad/runtime/support/am/__init__.py",
  "tinygrad_repo/tinygrad/runtime/support/am/amdev.py",
  "tinygrad_repo/tinygrad/runtime/support/am/ip.py",
  "tinygrad_repo/tinygrad/runtime/support/amd.py",
  "tinygrad_repo/tinygrad/runtime/support/compiler_amd.py",
  "tinygrad_repo/tinygrad/runtime/support/elf.py",
  "tinygrad_repo/tinygrad/runtime/support/hcq.py",
  "tinygrad_repo/tinygrad/runtime/support/llvm.py",
  "tinygrad_repo/tinygrad/runtime/support/memory.py",
  "tinygrad_repo/tinygrad/runtime/support/system.py",
  "tinygrad_repo/tinygrad/runtime/support/usb.py",
  "tinygrad_repo/tinygrad/schedule/__init__.py",
  "tinygrad_repo/tinygrad/schedule/grouper.py",
  "tinygrad_repo/tinygrad/schedule/kernelize.py",
  "tinygrad_repo/tinygrad/schedule/multi.py",
  "tinygrad_repo/tinygrad/schedule/rangeify.py",
  "tinygrad_repo/tinygrad/shape/__init__.py",
  "tinygrad_repo/tinygrad/shape/shapetracker.py",
  "tinygrad_repo/tinygrad/shape/view.py",
  "tinygrad_repo/tinygrad/tensor.py",
  "tinygrad_repo/tinygrad/uop/__init__.py",
  "tinygrad_repo/tinygrad/uop/decompositions.py",
  "tinygrad_repo/tinygrad/uop/mathtraits.py",
  "tinygrad_repo/tinygrad/uop/ops.py",
  "tinygrad_repo/tinygrad/uop/spec.py",
  "tinygrad_repo/tinygrad/uop/symbolic.py",
  "tinygrad_repo/tinygrad/uop/upat.py",
}


# Manifest exclusions
DEVELOPMENT_DIRECTORIES = {"docs", "examples", "site_scons"}

EXCLUDED_FILES = {
  ".gitattributes",
  ".gitmodules",
  ".lfsconfig",
  ".overlay_init",
  "Jenkinsfile",
  "common/prefix.py",
  "common/timeout.py",
  "common/transformations/coordinates.py",
  "frogpilot/classic_modeld/dmonitoringmodeld.py",
  "frogpilot/classic_modeld/get_model_metadata.py",
  "frogpilot/classic_modeld/models/dmonitoring_model.current",
  "frogpilot/classic_modeld/models/dmonitoring_model_q.dlc",
  "frogpilot/third_party/dateutil/zoneinfo/rebuild.py",
  "frogpilot/tinygrad_modeld/dmonitoringmodeld.py",
  "frogpilot/tinygrad_modeld/get_model_metadata.py",
  "frogpilot/tinygrad_modeld/models/dmonitoring_model.current",
  "frogpilot/tinygrad_modeld/models/dmonitoring_model_tinygrad.pkl",
  "frogpilot/ui/layouts/settings/toggle_metadata.py",
  "panda/crypto/sign.py",
  "panda/python/ccp.py",
  "panda/python/xcp.py",
  "panda/setup.py",
  "rednose_repo/rednose/helpers/chi2_lookup.py",
  "rednose_repo/rednose/helpers/chi2_lookup_table.npy",
  "rednose_repo/rednose/helpers/ekf_sym.py",
  "rednose_repo/rednose/helpers/sympy_helpers.py",
  "rednose_repo/setup.py",
  "selfdrive/car/docs.py",
  "selfdrive/locationd/models/live_kf.py",
  "selfdrive/modeld/get_model_metadata.py",
  "selfdrive/modeld/models/dmonitoring_model.current",
  "selfdrive/navd/set_destination.py",
  "selfdrive/ui/qt/spinner_larch64",
  "selfdrive/ui/qt/text_larch64",
  "selfdrive/ui/ui.py",
  "selfdrive/ui/update_translations.py",
  "system/hardware/tici/precise_power_measure.py",
  "system/manager/build.py",
  "system/qcomgpsd/nmeaport.py",
  "system/ugpsd.py",
}

EXCLUDED_PREFIXES = (
  ".devcontainer/",
  ".git/",
  ".github/",
  ".vscode/",
  "common/mock/",
  "frogpilot/third_party/reactivex/",
  "frogpilot/tools/",
  "opendbc/generator/",
  "release/",
  "scripts/",
  "selfdrive/controls/lib/lateral_mpc_lib/",
  "selfdrive/debug/",
)


# Verification contracts
EXPECTED_SYMLINKS = SOURCE_SYMLINKS | {
  "third_party/maplibre-native-qt/larch64/lib/libQMapLibre.so": "libQMapLibre.so.3.0.0",
}

NON_MANAGER_ELF_ENTRYPOINTS = {
  "selfdrive/pandad/pandad",
  "selfdrive/ui/_spinner",
  "selfdrive/ui/_text",
  "system/hardware/tici/updater",
}

REQUIRED_EXECUTABLES = NON_MANAGER_ELF_ENTRYPOINTS | {
  "frogpilot/navigation/mapd",
  "launch_chffrplus.sh",
  "launch_env.sh",
  "launch_openpilot.sh",
}


# Manifest construction
def relative_path(path: Path, root: Path) -> str:
  return path.relative_to(root).as_posix()


def is_shared_library(relative: str) -> bool:
  name = Path(relative).name
  return ".so." in name or name.endswith(".so")


def is_test_path(relative: str) -> bool:
  path = Path(relative)
  if any(part in {"test", "tests"} for part in path.parts):
    return True
  return path.name == "conftest.py" or path.name.startswith("test_") or path.name.endswith("_test.py")


def is_third_party_runtime(relative: str) -> bool:
  if relative == "third_party/libyuv/LICENSE":
    return True
  if relative == "third_party/snpe/larch64":
    return True
  if relative.startswith(("third_party/snpe/aarch64-ubuntu-gcc7.5/", "third_party/snpe/dsp/")):
    return is_shared_library(relative)
  if relative.startswith("third_party/acados/larch64/lib/"):
    return is_shared_library(relative)
  return relative == "third_party/maplibre-native-qt/larch64/lib/libQMapLibre.so.3.0.0"


def is_tinygrad_runtime(relative: str) -> bool:
  return relative in TINYGRAD_FILES


def is_runtime_file(path: Path, root: Path) -> bool:
  relative = relative_path(path, root)
  parts = Path(relative).parts

  if relative in CAMERAD_OPENCL_HEADERS:
    return (root / CAMERAD_OPENCL_PROGRAM).is_file()
  if relative in REQUIRED_FILES or relative in SOURCE_SYMLINKS or relative in TOOLS_FILES:
    return True
  if fnmatch.fnmatchcase(relative, SIGNAL_MARKER_GLOB):
    return True
  if relative in EXCLUDED_FILES or relative.startswith(EXCLUDED_PREFIXES) or is_test_path(relative):
    return False
  if any(part in DEVELOPMENT_DIRECTORIES for part in parts) or path.name.startswith(".") or path.name in {"Jenkinsfile", "SConstruct", "SConscript"}:
    return False
  if relative.startswith(("body/", "panda/board/")):
    return relative in FIRMWARE_FILES or relative in LEGAL_FILES
  if relative.startswith("third_party/"):
    return is_third_party_runtime(relative)
  if relative.startswith("tinygrad_repo/"):
    return is_tinygrad_runtime(relative)
  if relative.startswith("tools/"):
    return relative.startswith("tools/bodyteleop/") or relative in TOOLS_FILES
  if relative.startswith("selfdrive/ui/translations/"):
    return False
  if path.is_symlink():
    return True
  if is_shared_library(relative):
    return True
  if path.suffix.lower() in RUNTIME_SUFFIXES:
    return True
  return False


def tracked_files(source: Path, git_directory: Path) -> list[Path]:
  command = ["git", f"--git-dir={git_directory}", f"--work-tree={source}", "ls-files", "-z"]
  output = subprocess.run(command, check=True, capture_output=True).stdout
  return [source / os.fsdecode(relative) for relative in output.split(b"\0") if relative]


def generated_files(source: Path) -> list[Path]:
  paths = [source / relative for relative in GENERATED_FILES]
  for pattern in GENERATED_GLOBS:
    paths.extend(source.glob(pattern))
  return paths


def manifest(source: Path, git_directory: Path) -> list[Path]:
  candidates = set(tracked_files(source, git_directory) + generated_files(source))
  files = [path for path in candidates if (path.is_file() or path.is_symlink()) and is_runtime_file(path, source)]
  return sorted(files, key=lambda path: relative_path(path, source))


# Release operations
def release_tree(root: Path):
  for path in root.rglob("*"):
    relative = relative_path(path, root)
    if relative == ".git" or relative.startswith(".git/"):
      continue
    yield path


def copy_file(source: Path, destination: Path) -> None:
  destination.parent.mkdir(parents=True, exist_ok=True)
  if source.is_symlink():
    destination.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
  else:
    shutil.copy2(source, destination)


def runtime_dbc_files(root: Path) -> set[str]:
  code = """
from openpilot.selfdrive.car.interfaces import get_interface_attr

names = set()
for platform_dbc in get_interface_attr("DBC", combine_brands=True).values():
  names.update(name for name in platform_dbc.values() if name is not None)
print("\\n".join(sorted(names)))
"""
  environment = os.environ.copy()
  environment["PYTHONPATH"] = str(root)
  result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root, env=environment, check=True, stdout=subprocess.PIPE, text=True)
  return {f"opendbc/{name}.dbc" for name in result.stdout.splitlines()}


def prune_dbcs(root: Path) -> int:
  required = runtime_dbc_files(root)
  removed = 0
  for path in (root / "opendbc").glob("*.dbc"):
    if relative_path(path, root) not in required:
      path.unlink()
      removed += 1
  return removed


def strip_debug_sections(root: Path) -> tuple[int, int]:
  strip = shutil.which("llvm-strip")
  if strip is None:
    raise RuntimeError("llvm-strip is required to prepare a production release")

  stripped = 0
  bytes_removed = 0
  for path in sorted(release_tree(root)):
    if not path.is_file() or path.is_symlink():
      continue
    # llvm-strip breaks Qualcomm's DSP-loadable binaries.
    if relative_path(path, root).startswith("third_party/snpe/dsp/"):
      continue
    with path.open("rb") as file:
      if file.read(4) != b"\x7fELF":
        continue
    before = path.stat().st_size
    subprocess.run([strip, "--strip-debug", str(path)], check=True)
    bytes_removed += before - path.stat().st_size
    stripped += 1
  return stripped, bytes_removed


# Release verification
def verify(root: Path) -> None:
  runtime_opencl_headers = CAMERAD_OPENCL_HEADERS if (root / CAMERAD_OPENCL_PROGRAM).is_file() else set()
  required_files = REQUIRED_FILES | runtime_opencl_headers

  missing = [relative for relative in sorted(required_files) if not (root / relative).is_file()]
  if missing:
    raise RuntimeError(f"required release file is missing: {missing[0]}")
  if not (root / "prebuilt").is_file():
    raise RuntimeError("prebuilt release marker is missing")

  for relative in sorted(required_files):
    path = root / relative
    if path.stat().st_size == 0:
      raise RuntimeError(f"required release file is empty: {relative}")

  broken_links = [path for path in release_tree(root) if path.is_symlink() and not path.exists()]
  if broken_links:
    raise RuntimeError(f"broken release symlink: {relative_path(broken_links[0], root)}")
  symlinks = {relative_path(path, root): os.readlink(path) for path in release_tree(root) if path.is_symlink()}
  if symlinks != EXPECTED_SYMLINKS:
    difference = sorted(symlinks.keys() ^ EXPECTED_SYMLINKS.keys())
    if not difference:
      difference = sorted(relative for relative, target in symlinks.items() if target != EXPECTED_SYMLINKS[relative])
    raise RuntimeError(f"unexpected release symlink set: {difference[0]}")
  release_root = root.resolve()
  for relative in sorted(EXPECTED_SYMLINKS):
    target = (root / relative).resolve()
    if not target.exists() or not target.is_relative_to(release_root):
      raise RuntimeError(f"release symlink escapes or has no target: {relative}")

  for relative in sorted(REQUIRED_EXECUTABLES):
    path = root / relative
    if not path.is_file() or not os.access(path, os.X_OK):
      raise RuntimeError(f"required executable is not executable: {relative}")

  import_check = """
import glob
import importlib
import os
import panda
import pickle
import shutil
import subprocess
from openpilot.system.manager.process import DaemonProcess, NativeProcess, PythonProcess
from openpilot.system.manager.process_config import managed_processes

for process in managed_processes.values():
  if isinstance(process, NativeProcess) and process.enabled:
    command = process.cmdline[0]
    if command == "env":
      command = next(argument for argument in process.cmdline[1:] if "=" not in argument)
    path = os.path.join(os.getcwd(), process.cwd, command) if command.startswith("./") else shutil.which(command)
    assert path is not None and os.path.isfile(path) and os.access(path, os.X_OK), (process.name, path)
    with open(path, "rb") as file:
      is_elf = file.read(4) == b"\x7fELF"
    if is_elf:
      dynamic = subprocess.run(["readelf", "--dynamic", "--wide", path], check=True, capture_output=True, text=True).stdout
      if "(NEEDED)" in dynamic:
        dependencies = subprocess.run(["ldd", path], capture_output=True, text=True)
        resolved = dependencies.returncode == 0 and "not found" not in dependencies.stdout and "not found" not in dependencies.stderr
        assert resolved, (process.name, dependencies.stdout, dependencies.stderr)
  elif isinstance(process, PythonProcess) and process.enabled:
    importlib.import_module(process.module)
  elif isinstance(process, DaemonProcess) and process.enabled:
    importlib.import_module(process.module)

for filename in glob.glob("frogpilot/tinygrad_modeld/models/*_tinygrad.pkl"):
  with open(filename, "rb") as file:
    pickle.load(file)
"""
  environment = os.environ.copy()
  environment["PYTHONPATH"] = str(root)
  subprocess.run([sys.executable, "-B", "-c", import_check], cwd=root, env=environment, check=True)

  missing_dbcs = [relative for relative in sorted(runtime_dbc_files(root)) if not (root / relative).is_file()]
  if missing_dbcs:
    raise RuntimeError(f"runtime DBC is missing: {missing_dbcs[0]}")

  sqlite_check = """
import sqlite3
connection = sqlite3.connect("frogpilot/assets/city_lookup.sqlite")
assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
"""
  subprocess.run([sys.executable, "-B", "-c", sqlite_check], cwd=root, check=True)

  forbidden_suffixes = {".a", ".c", ".cc", ".cpp", ".h", ".hpp", ".o", ".onnx", ".os", ".pxd", ".pyx", ".qrc", ".ts"}
  for path in release_tree(root):
    if not path.is_file() or path.is_symlink():
      continue
    if path.suffix in forbidden_suffixes and relative_path(path, root) not in (runtime_opencl_headers | {"common/version.h"}):
      raise RuntimeError(f"build input entered release: {relative_path(path, root)}")
    with path.open("rb") as file:
      if file.read(4) != b"\x7fELF":
        continue
    header = subprocess.run(["readelf", "--file-header", str(path)], check=True, capture_output=True, text=True).stdout
    if "AArch64" not in header and "QUALCOMM DSP" not in header.upper():
      raise RuntimeError(f"wrong ELF architecture in {relative_path(path, root)}")
    sections = subprocess.run(["readelf", "--sections", "--wide", str(path)], check=True, capture_output=True, text=True).stdout
    if ".debug_" in sections or ".zdebug_" in sections:
      raise RuntimeError(f"ELF debug sections remain in {relative_path(path, root)}")
    relative = relative_path(path, root)
    if relative in NON_MANAGER_ELF_ENTRYPOINTS:
      dynamic = subprocess.run(["readelf", "--dynamic", "--wide", str(path)], check=True, capture_output=True, text=True).stdout
      if "(NEEDED)" in dynamic:
        dependencies = subprocess.run(["ldd", str(path)], cwd=path.parent, capture_output=True, text=True)
        if dependencies.returncode != 0 or "not found" in dependencies.stdout or "not found" in dependencies.stderr:
          raise RuntimeError(f"unresolved ELF dependency in {relative}:\n{dependencies.stdout}{dependencies.stderr}")

  for relative in (
    "launch_chffrplus.sh",
    "launch_env.sh",
    "launch_openpilot.sh",
    "frogpilot/classic_modeld/classic_modeld",
    "selfdrive/modeld/modeld",
  ):
    subprocess.run(["bash", "-n", str(root / relative)], check=True)

  forbidden = [
    path for path in release_tree(root)
    if path.name == ".overlay_init" or path.name == "__pycache__" or is_test_path(relative_path(path, root))
  ]
  if forbidden:
    raise RuntimeError(f"development file entered release: {relative_path(forbidden[0], root)}")


# Release orchestration
def materialize(source: Path, destination: Path) -> None:
  source = source.resolve()
  destination = destination.resolve()
  unexpected = [path for path in destination.iterdir() if path.name != ".git"]
  if unexpected:
    raise RuntimeError(f"release destination is not empty: {unexpected[0]}")

  files = manifest(source, destination / ".git")
  for path in files:
    copy_file(path, destination / relative_path(path, source))

  maplibre = destination / "third_party/maplibre-native-qt/larch64/lib/libQMapLibre.so"
  maplibre.parent.mkdir(parents=True, exist_ok=True)
  maplibre.symlink_to("libQMapLibre.so.3.0.0")

  (destination / "prebuilt").touch()
  removed_dbcs = prune_dbcs(destination)
  stripped, bytes_removed = strip_debug_sections(destination)
  verify(destination)
  print(f"Prepared {len(files) + 2 - removed_dbcs} files; removed {removed_dbcs} unused DBCs; stripped {stripped} ELFs and removed {bytes_removed} debug bytes")


# Command-line entry point
def main() -> None:
  parser = argparse.ArgumentParser(description="Materialize and verify a minimal prebuilt FrogPilot release")
  parser.add_argument("source", type=Path)
  parser.add_argument("destination", type=Path)
  args = parser.parse_args()
  materialize(args.source, args.destination)


if __name__ == "__main__":
  main()
