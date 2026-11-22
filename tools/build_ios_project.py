import json
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = json.loads((ROOT / 'release.json').read_text())
    folder = ROOT / 'outputs/ios'
    project = folder / 'LectureRecorder.xcodeproj'
    project.mkdir(parents=True, exist_ok=True)
    info = {
        'CFBundleDevelopmentRegion': 'ru', 'CFBundleDisplayName': 'Запись лекций',
        'CFBundleExecutable': '$(EXECUTABLE_NAME)', 'CFBundleIdentifier': '$(PRODUCT_BUNDLE_IDENTIFIER)',
        'CFBundleName': '$(PRODUCT_NAME)', 'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': version['version'], 'CFBundleVersion': str(version['code']),
        'LSRequiresIPhoneOS': True, 'UILaunchScreen': {}, 'UIBackgroundModes': ['audio'],
        'UIUserInterfaceStyle': 'Dark',
        'NSMicrophoneUsageDescription': 'Запись лекций микрофоном телефона. Аудио сохраняется на устройстве.',
        'NSLocalNetworkUsageDescription': 'Подключение к твоему Mac для переноса записей, расшифровок и конспектов.',
        'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
        'UISupportedInterfaceOrientations': ['UIInterfaceOrientationPortrait', 'UIInterfaceOrientationLandscapeLeft', 'UIInterfaceOrientationLandscapeRight'],
        'UISupportedInterfaceOrientations~ipad': ['UIInterfaceOrientationPortrait', 'UIInterfaceOrientationPortraitUpsideDown', 'UIInterfaceOrientationLandscapeLeft', 'UIInterfaceOrientationLandscapeRight'],
    }
    (folder / 'LectureRecorder/Info.plist').write_bytes(plistlib.dumps(info))
    sources = sorted((folder / 'LectureRecorder').glob('*.swift'))
    objects = []
    for i, file in enumerate(sources, 100):
        objects.append(f'{i:024X} = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = LectureRecorder/{file.name}; sourceTree = "<group>"; }};')
        objects.append(f'{i+100:024X} = {{isa = PBXBuildFile; fileRef = {i:024X}; }};')
    refs = ','.join(f'{i:024X}' for i in range(100, 100 + len(sources)))
    builds = ','.join(f'{i:024X}' for i in range(200, 200 + len(sources)))
    config = 'IPHONEOS_DEPLOYMENT_TARGET = 16.0; SDKROOT = iphoneos; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = "1,2"; PRODUCT_BUNDLE_IDENTIFIER = ru.ilya.lecturerecorder.ios; PRODUCT_NAME = "$(TARGET_NAME)"; INFOPLIST_FILE = LectureRecorder/Info.plist; CODE_SIGN_STYLE = Automatic; SUPPORTS_MACCATALYST = NO; ENABLE_USER_SCRIPT_SANDBOXING = YES;'
    for number, name, extra in [(10, 'Debug', 'SWIFT_OPTIMIZATION_LEVEL = "-Onone";'), (11, 'Release', 'SWIFT_COMPILATION_MODE = wholemodule; SWIFT_OPTIMIZATION_LEVEL = "-O";')]:
        objects.append(f'{number:024X} = {{isa = XCBuildConfiguration; name = {name}; buildSettings = {{{config} {extra}}}; }};')
    objects += [
        f'{1:024X} = {{isa = PBXProject; attributes = {{LastUpgradeCheck = 1600; }}; buildConfigurationList = {12:024X}; compatibilityVersion = "Xcode 14.0"; developmentRegion = ru; knownRegions = (ru, en, Base); mainGroup = {2:024X}; productRefGroup = {3:024X}; projectDirPath = ""; projectRoot = ""; targets = ({4:024X}); }};',
        f'{2:024X} = {{isa = PBXGroup; children = ({refs},{3:024X}); sourceTree = "<group>"; }};',
        f'{3:024X} = {{isa = PBXGroup; children = ({5:024X}); name = Products; sourceTree = "<group>"; }};',
        f'{4:024X} = {{isa = PBXNativeTarget; buildConfigurationList = {9:024X}; buildPhases = ({6:024X},{7:024X},{8:024X}); buildRules = (); dependencies = (); name = LectureRecorder; productName = LectureRecorder; productReference = {5:024X}; productType = "com.apple.product-type.application"; }};',
        f'{5:024X} = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = LectureRecorder.app; sourceTree = BUILT_PRODUCTS_DIR; }};',
        f'{6:024X} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({builds}); runOnlyForDeploymentPostprocessing = 0; }};',
        f'{7:024X} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};',
        f'{8:024X} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};',
        f'{9:024X} = {{isa = XCConfigurationList; buildConfigurations = ({10:024X},{11:024X}); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }};',
        f'{12:024X} = {{isa = XCConfigurationList; buildConfigurations = ({13:024X},{14:024X}); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }};',
        f'{13:024X} = {{isa = XCBuildConfiguration; name = Debug; buildSettings = {{SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 16.0;}}; }};',
        f'{14:024X} = {{isa = XCBuildConfiguration; name = Release; buildSettings = {{SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 16.0;}}; }};',
    ]
    (project / 'project.pbxproj').write_text('// !$*UTF8*$!\n{archiveVersion = 1; classes = {}; objectVersion = 56; objects = {\n' + '\n'.join(objects) + f'\n}}; rootObject = {1:024X}; }}\n')
    schemes = project / 'xcshareddata/xcschemes'
    schemes.mkdir(parents=True, exist_ok=True)
    ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{4:024X}" BuildableName="LectureRecorder.app" BlueprintName="LectureRecorder" ReferencedContainer="container:LectureRecorder.xcodeproj"/>'
    (schemes / 'LectureRecorder.xcscheme').write_text(f'<?xml version="1.0" encoding="UTF-8"?><Scheme LastUpgradeVersion="1600" version="1.3"><BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{ref}</BuildActionEntry></BuildActionEntries></BuildAction><LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></LaunchAction><ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></ProfileAction><AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/></Scheme>\n')
    print(project)


if __name__ == '__main__':
    main()
