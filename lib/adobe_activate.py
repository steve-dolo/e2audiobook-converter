"""Link ACSM Input to an Adobe ID without the calibre GUI. Run via bin/adobe-activate."""
import getpass
import os
import sys
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(os.environ["EBOOKS_REPO"])
PLUGINS = REPO / ".calibre-config" / "plugins"
ACCOUNT = PLUGINS / "ACSMInput" / "account"
LIBS = REPO / "tools" / "deacsm"
KEYS = REPO / "keys"
ADE_VERSION = 1  # "ADE 2.0.1": the plugin's recommended default, gives the older (DeDRM-friendly) DRM


def load_plugin_libs():
    """Unpack the installed plugin (and its bundled oscrypto/asn1crypto) so its modules import standalone."""
    plugin_zip = PLUGINS / "ACSM Input.zip"
    if not plugin_zip.exists():
        sys.exit("ACSM Input plugin not installed; run bin/setup first.")
    if not LIBS.exists() or LIBS.stat().st_mtime < plugin_zip.stat().st_mtime:
        with zipfile.ZipFile(plugin_zip) as z:
            z.extractall(LIBS)
        for dep in ("oscrypto", "asn1crypto"):
            with zipfile.ZipFile(LIBS / f"{dep}.zip") as z:
                z.extractall(LIBS / dep)
    for p in (LIBS / "asn1crypto", LIBS / "oscrypto", LIBS):
        sys.path.insert(0, str(p))
    import libadobe
    ACCOUNT.mkdir(parents=True, exist_ok=True)
    libadobe.update_account_path(str(ACCOUNT))


def backup():
    from libadobeAccount import exportAccountEncryptionKeyDER, getAccountUUID
    KEYS.mkdir(exist_ok=True)
    zip_path = KEYS / f"adobe-activation-{date.today()}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for name in ("activation.xml", "device.xml", "devicesalt"):
            z.write(ACCOUNT / name, name)
    der_path = KEYS / f"adobe-key-{getAccountUUID()}.der"
    exportAccountEncryptionKeyDER(str(der_path))
    print(f"Backed up activation -> {zip_path.relative_to(REPO)}")
    print(f"Exported decryption key -> {der_path.relative_to(REPO)}")


def status():
    from libadobeAccount import getAccountUUID
    from lxml import etree
    ns = {"a": "http://ns.adobe.com/adept"}
    act = ACCOUNT / "activation.xml"
    tree = etree.parse(str(act)) if act.exists() else None
    # A failed login leaves a partial activation.xml behind; only the token means "activated".
    if tree is None or tree.find(".//a:activationToken", namespaces=ns) is None:
        print("Not activated.")
        return False
    login = tree.findtext(".//a:credentials/a:username", namespaces=ns) or "(anonymous)"
    print(f"Activated: Adobe ID {login}, account {getAccountUUID()}")
    return True


def activate():
    try:
        _activate()
    except BaseException:
        for name in ("activation.xml", "device.xml", "devicesalt"):
            (ACCOUNT / name).unlink(missing_ok=True)
        raise


def _activate():
    from libadobe import createDeviceKeyFile
    from libadobeAccount import activateDevice, createDeviceFile, createUser, signIn

    mail = input("ByteBooks / Adobe ID email: ").strip()
    if not mail:
        sys.exit("Aborted: an Adobe ID is required (anonymous auths can't be moved later).")
    passwd = getpass.getpass("Password (not echoed): ")
    if not passwd:
        sys.exit("Aborted: empty password.")

    createDeviceKeyFile()
    createDeviceFile(False, ADE_VERSION)
    ok, resp = createUser(ADE_VERSION, None)
    if not ok:
        sys.exit(f"Couldn't create user: {resp}")
    ok, resp = signIn("AdobeID", mail, passwd)
    if not ok:
        if "does not exist" in str(resp) or "RESET_PW_REQUIRED" in str(resp):
            resp = (f"{resp}\n\nSince June 2026 ebook sign-in is run by ByteBooks, not Adobe: a plain Adobe ID is "
                    "unknown here until it has a ByteBooks ID. Create or migrate one at "
                    "https://dtsbytebooks.com/transition-help, then re-run with those credentials.")
        sys.exit(f"Login unsuccessful: {resp}")
    ok, resp = activateDevice(ADE_VERSION, None)
    if not ok:
        sys.exit(f"Couldn't activate device: {resp}")
    print(f"Authorized to Adobe ID {mail}")


def main():
    load_plugin_libs()
    if "--status" in sys.argv:
        if status():
            backup()
        return
    if status():
        sys.exit("Already activated. Re-activating uses up another of the account's limited activations; "
                 "delete .calibre-config/plugins/ACSMInput/account/ first if you really mean to.")
    activate()
    status()
    backup()


main()
