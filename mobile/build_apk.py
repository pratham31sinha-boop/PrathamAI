#!/usr/bin/env python3
"""
Pratham AI Android Standalone APK Builder
Directly uses the official Android SDK toolchain: aapt2, javac, d8, zipalign, apksigner.
Builds the standalone APK without relying on daemon sockets or /proc.
"""
import os
import sys
import subprocess
import shutil
import zipfile

def run_cmd(cmd, cwd=None):
    print(f"[BUILD] Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    res = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERROR] stdout:\n{res.stdout}\nstderr:\n{res.stderr}")
        raise RuntimeError(f"Command failed with exit code {res.returncode}")
    if res.stdout.strip():
        print(f"[OUT] {res.stdout.strip()[:300]}")
    return res.stdout

def build_apk():
    build_tools = "/root/android-sdk/build-tools/35.0.0"
    platform_dir = "/root/android-sdk/platforms/android-35"
    android_jar = os.path.join(platform_dir, "android.jar")
    aapt2 = os.path.join(build_tools, "aapt2")
    d8 = os.path.join(build_tools, "d8")
    zipalign = os.path.join(build_tools, "zipalign")
    apksigner = os.path.join(build_tools, "apksigner")

    workspace = "/workspace/bold-curie"
    mobile_dir = os.path.join(workspace, "mobile")
    app_dir = os.path.join(mobile_dir, "android", "app")
    src_dir = os.path.join(app_dir, "src", "main")
    res_dir = os.path.join(src_dir, "res")
    assets_dir = os.path.join(src_dir, "assets")
    manifest = os.path.join(src_dir, "AndroidManifest.xml")
    java_file = os.path.join(src_dir, "java", "com", "prathamai", "mobile", "MainActivity.java")

    out_build = os.path.join(app_dir, "build_manual")
    if os.path.exists(out_build):
        shutil.rmtree(out_build)
    os.makedirs(out_build, exist_ok=True)

    compiled_res_dir = os.path.join(out_build, "compiled_res")
    gen_dir = os.path.join(out_build, "gen")
    classes_dir = os.path.join(out_build, "classes")
    os.makedirs(compiled_res_dir, exist_ok=True)
    os.makedirs(gen_dir, exist_ok=True)
    os.makedirs(classes_dir, exist_ok=True)

    # 1. Compile resources with aapt2
    print("[1/7] Compiling Android resources with aapt2...")
    res_zips = []
    for root, dirs, files in os.walk(res_dir):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, res_dir)
            out_zip = os.path.join(compiled_res_dir, rel_path.replace(os.sep, "_") + ".flat")
            run_cmd([aapt2, "compile", full_path, "-o", compiled_res_dir])

    compiled_flats = [os.path.join(compiled_res_dir, f) for f in os.listdir(compiled_res_dir) if f.endswith(".flat")]
    print(f"Compiled {len(compiled_flats)} resource flats.")

    # 2. Link resources with aapt2
    print("[2/7] Linking resources & generating R.java...")
    unaligned_apk = os.path.join(out_build, "app-unaligned.apk")
    link_cmd = [
        aapt2, "link",
        "-I", android_jar,
        "--manifest", manifest,
        "--java", gen_dir,
        "-o", unaligned_apk,
        "-A", assets_dir,
        "--auto-add-overlay"
    ] + compiled_flats
    run_cmd(link_cmd)

    # 3. Find generated R.java
    r_java = None
    for root, dirs, files in os.walk(gen_dir):
        for f in files:
            if f == "R.java":
                r_java = os.path.join(root, f)
                break
    print(f"Generated R.java: {r_java}")

    # 4. Compile Java sources with javac
    print("[3/7] Compiling Java source with javac...")
    javac_cmd = [
        "javac",
        "-source", "17",
        "-target", "17",
        "-cp", android_jar,
        "-d", classes_dir,
        java_file
    ]
    if r_java:
        javac_cmd.append(r_java)
    run_cmd(javac_cmd)

    # 5. Dex with d8
    print("[4/7] Generating classes.dex with d8...")
    class_files = []
    for root, dirs, files in os.walk(classes_dir):
        for f in files:
            if f.endswith(".class"):
                class_files.append(os.path.join(root, f))
    print(f"Found {len(class_files)} class files to dex.")

    dex_dir = os.path.join(out_build, "dex")
    os.makedirs(dex_dir, exist_ok=True)
    d8_cmd = [d8, "--release", "--output", dex_dir, "--lib", android_jar] + class_files
    run_cmd(d8_cmd)

    classes_dex = os.path.join(dex_dir, "classes.dex")
    if not os.path.exists(classes_dex):
        raise RuntimeError("classes.dex was not generated!")

    # 6. Add classes.dex into unaligned apk
    print("[5/7] Adding classes.dex into APK...")
    with zipfile.ZipFile(unaligned_apk, 'a') as apk_zip:
        apk_zip.write(classes_dex, "classes.dex")

    # 7. Zipalign
    print("[6/7] Running zipalign...")
    aligned_apk = os.path.join(out_build, "app-aligned.apk")
    run_cmd([zipalign, "-f", "-p", "4", unaligned_apk, aligned_apk])

    # 8. Create debug keystore if not exists and sign with apksigner
    print("[7/7] Signing APK with apksigner...")
    keystore_path = os.path.join(out_build, "debug.keystore")
    if not os.path.exists(keystore_path):
        keytool_cmd = [
            "keytool", "-genkeypair", "-v",
            "-keystore", keystore_path,
            "-storepass", "android",
            "-alias", "androiddebugkey",
            "-keypass", "android",
            "-keyalg", "RSA",
            "-keysize", "2048",
            "-validity", "10000",
            "-dname", "CN=PrathamAI,OU=Engineering,O=PrathamAI,C=US"
        ]
        run_cmd(keytool_cmd)

    final_apk = os.path.join(mobile_dir, "PrathamAI.apk")
    apk_out_dir = os.path.join(app_dir, "build", "outputs", "apk", "release")
    os.makedirs(apk_out_dir, exist_ok=True)
    final_release_apk = os.path.join(apk_out_dir, "PrathamAI-release.apk")

    sign_cmd = [
        apksigner, "sign",
        "--ks", keystore_path,
        "--ks-pass", "pass:android",
        "--ks-key-alias", "androiddebugkey",
        "--key-pass", "pass:android",
        "--out", final_apk,
        aligned_apk
    ]
    run_cmd(sign_cmd)

    shutil.copy2(final_apk, final_release_apk)
    size_mb = os.path.getsize(final_apk) / (1024 * 1024)
    print(f"\n✅ Standalone APK Successfully Built!")
    print(f"📦 Output path: {final_apk}")
    print(f"📦 Release path: {final_release_apk}")
    print(f"📊 Size: {size_mb:.2f} MB")
    return final_apk

if __name__ == "__main__":
    build_apk()
