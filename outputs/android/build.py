"""Build the Android APK with the local SDK and JDK 21 or newer."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
from xml.etree import ElementTree
import zipfile


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
TOOLS = PROJECT / "work/android-tools"
CACHE = PROJECT / "work/android-deps"
PACKAGE = "ru.ilya.lecturerecorder"
ANDROID = "{http://schemas.android.com/apk/res/android}"
ABIS = {"arm64-v8a", "armeabi-v7a", "x86", "x86_64"}


def download(dependency):
    target = CACHE / dependency["file"]
    temp = target.with_suffix(target.suffix + ".part")
    for candidate in (target, temp):
        if candidate == temp:
            with urllib.request.urlopen(dependency["url"], timeout=90) as response:
                with temp.open("wb") as output:
                    shutil.copyfileobj(response, output)
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == dependency["sha256"]:
            if candidate == temp:
                temp.replace(target)
            return target
    raise SystemExit(f"Контрольная сумма отличается: {target.name}")


def prepare_dependencies(build):
    CACHE.mkdir(parents=True, exist_ok=True)
    native = {}
    jars = []
    dexer = None
    for dependency in json.loads((ROOT / "dependencies.json").read_text()):
        archive = download(dependency)
        if dependency.get("scope") == "build":
            dexer = archive
            continue
        if archive.suffix != ".aar":
            jars.append(archive)
            continue
        abis = ABIS.intersection(dependency.get("abis", ABIS))
        with zipfile.ZipFile(archive) as package:
            jar = build / f"{archive.stem}.jar"
            jar.write_bytes(package.read("classes.jar"))
            jars.append(jar)
            for name in package.namelist():
                parts = name.split("/")
                if len(parts) == 3 and parts[0] == "jni" and parts[1] in abis and name.endswith(".so"):
                    entry = "lib/" + "/".join(parts[1:])
                    if entry in native:
                        raise SystemExit(f"Дублирующаяся библиотека: {entry}")
                    native[entry] = package.read(name)
    return dexer, jars, native


def manifest_for_preview(build):
    ElementTree.register_namespace("android", ANDROID[1:-1])
    tree = ElementTree.parse(ROOT / "AndroidManifest.xml")
    manifest = tree.getroot()
    manifest.set("package", PACKAGE + ".preview")
    app = manifest.find("application")
    app.set(ANDROID + "label", "На полях · ИИ")
    for component in app:
        name = component.get(ANDROID + "name", "")
        if name.startswith("."):
            component.set(ANDROID + "name", PACKAGE + name)
        authority = component.get(ANDROID + "authorities")
        if authority:
            component.set(ANDROID + "authorities", authority.replace(PACKAGE + ".", PACKAGE + ".preview.", 1))
    target = build / "AndroidManifest.xml"
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="Собрать отдельное приложение для проверки")
    parser.add_argument("--offline-models", type=Path, metavar="DIR",
                        help="Собрать ещё один APK со встроенными моделями речи и конспекта из этой папки")
    args = parser.parse_args()
    if args.preview and args.offline_models:
        parser.error("Автономный APK собирается для основного приложения")
    version = json.loads((PROJECT / "release.json").read_text())
    TOOLS.mkdir(parents=True, exist_ok=True)
    jdk = Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else next((TOOLS / "jdk").glob("*/Contents/Home"))
    sdk_root = Path(os.environ["ANDROID_SDK_ROOT"]) if os.environ.get("ANDROID_SDK_ROOT") else None
    default_platform = (sdk_root / "platforms" if sdk_root else TOOLS / "platform") / "android-36/android.jar"
    platform = Path(os.environ.get("ANDROID_PLATFORM_JAR", default_platform))
    build_tools = os.environ.get("ANDROID_BUILD_TOOLS")
    if build_tools:
        tools = Path(build_tools)
    elif sdk_root:
        tools = sorted((sdk_root / "build-tools").iterdir())[-1]
    else:
        tools = TOOLS / "build-tools/android-16"
    env = dict(os.environ, JAVA_HOME=str(jdk), PATH=str(jdk / "bin") + os.pathsep + os.environ["PATH"])

    def run(*command):
        subprocess.run([str(part) for part in command], env=env, check=True)

    with tempfile.TemporaryDirectory(prefix="android-build-", dir=PROJECT / "work") as directory:
        build = Path(directory)
        dexer, jars, native = prepare_dependencies(build)
        resources = build / "res"
        shutil.copytree(ROOT / "res", resources)
        run(tools / "aapt2", "compile", "--dir", resources, "-o", build / "res.zip")
        generated = build / "generated"
        generated.mkdir()
        manifest = manifest_for_preview(build) if args.preview else ROOT / "AndroidManifest.xml"
        assets = build / "assets"
        shutil.copytree(ROOT / "assets", assets)
        config = {"repository": version["repository"], "client_id": version["updates"]["client_id"]}
        (assets / "update-config.json").write_text(json.dumps(config))
        version_code = version["android_preview"]["code"] if args.preview else version["code"]
        apk = build / "base.apk"
        run(tools / "aapt2", "link", "-o", apk, "-I", platform, "--manifest", manifest,
            "--java", generated, "-A", assets, "--custom-package", PACKAGE, "--version-code", version_code,
            "--version-name", version["version"], build / "res.zip")

        classes = build / "classes"
        classes.mkdir()
        classpath = os.pathsep.join(map(str, [platform, *jars]))
        run(jdk / "bin/javac", "-encoding", "UTF-8", "--release", "8", "-classpath", classpath,
            "-d", classes, *sorted(ROOT.glob("src/**/*.java")), *generated.glob("**/*.java"))
        classes_jar = build / "classes.jar"
        with zipfile.ZipFile(classes_jar, "w") as package:
            for path in sorted(classes.rglob("*.class")):
                package.write(path, path.relative_to(classes))
        run(jdk / "bin/java", "-cp", dexer, "com.android.tools.r8.D8",
            "--release", "--min-api", "26", "--lib", platform,
            "--output", build, classes_jar, *jars)
        with zipfile.ZipFile(apk, "a", compression=zipfile.ZIP_DEFLATED) as package:
            for path in sorted(build.glob("classes*.dex")):
                package.write(path, path.name)
            for name, data in native.items():
                package.writestr(name, data)
            added = set(package.namelist())
            for jar in jars:
                with zipfile.ZipFile(jar) as dependency:
                    for name in dependency.namelist():
                        if name in added or name.endswith(("/", ".class")) or name.startswith("META-INF/versions/"):
                            continue
                        if name.startswith(("kotlin/", "META-INF/services/")):
                            package.writestr(name, dependency.read(name))
                            added.add(name)
                    for name in dependency.namelist():
                        if name.rsplit("/", 1)[-1].upper().startswith(("LICENSE", "NOTICE", "COPYING")):
                            package.writestr(f"assets/licenses/{jar.stem}/{name}", dependency.read(name))
        key_variable = "LECTURE_PREVIEW_KEYSTORE" if args.preview else "LECTURE_KEYSTORE"
        key_default = "preview.keystore" if args.preview else "lectures.keystore"
        key = Path(os.environ.get(key_variable, TOOLS / key_default))
        if args.preview and "LECTURE_PREVIEW_KEY_PASSWORD" in env:
            env["LECTURE_KEY_PASSWORD"] = env["LECTURE_PREVIEW_KEY_PASSWORD"]
        env.setdefault("LECTURE_KEY_PASSWORD", "android")
        if not key.exists():
            if key_variable in os.environ:
                raise SystemExit("Указанный ключ подписи не найден")
            run(jdk / "bin/keytool", "-genkeypair", "-keystore", key, "-storepass:env", "LECTURE_KEY_PASSWORD",
                "-keypass:env", "LECTURE_KEY_PASSWORD", "-alias", "lectures", "-dname", "CN=Ilya Lecture Recorder",
                "-keyalg", "RSA", "-validity", "10000")
            key.chmod(0o600)
        output = ROOT / ("Запись лекций · ИИ.apk" if args.preview else "Запись лекций.apk")
        def sign(destination):
            aligned = build / "aligned.apk"
            run(tools / "zipalign", "-P", "16", "-f", "4", apk, aligned)
            run(tools / "apksigner", "sign", "--ks", key, "--ks-pass", "env:LECTURE_KEY_PASSWORD", "--out", destination, aligned)
            run(tools / "apksigner", "verify", destination)
            print(f"APK ready: {destination}")

        sign(output)
        if args.offline_models:
            models = {
                "gigaam-v3-e2e-ctc.int8.onnx": "2e3fcb7a7b66030336fd10c2fcfb033bd1dc7e1bf238fe5cfd83b1d0cfc9d28e",
                "qwen3-0.6b-int4.litertlm": "bf1aba9ce8d963124407353c6aa4cbf72eba78db21ae133de983eac672ce83e0",
            }
            with zipfile.ZipFile(apk, "a") as package:
                for name, sha in models.items():
                    path = args.offline_models / name
                    with path.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                            raise ValueError(f"Не совпала контрольная сумма {name}")
                    package.write(path, "assets/models/" + name, compress_type=zipfile.ZIP_STORED)
            sign(ROOT / "lecture-recorder-offline.apk")


if __name__ == "__main__":
    main()
