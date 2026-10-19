from wimm.core.cache_items import TreeEntry, TreeListing, items_for
from wimm.model import CacheItem, CacheItemKind, CacheRest
from wimm.model.disk import CacheKind

from .cache_items_helpers import DEV, d, f, ln, regular_total

SDK_ROOT = "/home/u/Android/Sdk"
AVD_ROOT = "/home/u/.android/avd"


def _sdk_entries() -> list[TreeEntry]:
    return [
        d("platforms"),
        d("platforms/android-35"),
        f("platforms/android-35/package.xml", 1000),
        f("platforms/android-35/android.jar", 9000),
        d("platforms/android-35/data"),
        f("platforms/android-35/data/res.bin", 500),
        d("build-tools"),
        d("build-tools/35.0.0"),
        f("build-tools/35.0.0/package.xml", 800),
        f("build-tools/35.0.0/aapt", 5000),
        d("system-images"),
        d("system-images/android-35"),
        d("system-images/android-35/google_apis"),
        d("system-images/android-35/google_apis/x86_64"),
        f("system-images/android-35/google_apis/x86_64/package.xml", 700),
        f("system-images/android-35/google_apis/x86_64/system.img", 20000),
        d("cmdline-tools"),
        d("cmdline-tools/latest"),
        f("cmdline-tools/latest/package.xml", 600),
        f("cmdline-tools/latest/sdkmanager", 3000),
        d("licenses"),
        f("licenses/package.xml", 100),
        f("licenses/android-sdk-license", 40),
        d(".temp"),
        f(".temp/partial.zip", 300),
    ]


def _sdk(extra: tuple[TreeEntry, ...] = ()) -> TreeListing:
    return TreeListing(root=SDK_ROOT, entries=(*_sdk_entries(), *extra))


def _split(listing: TreeListing, kind: CacheKind) -> tuple[tuple[CacheItem, ...], CacheRest]:
    return items_for(kind=kind, listing=listing, size=regular_total(listing))


def test_sdk_items_are_the_package_folders_with_sdkmanager_ids() -> None:
    items, _ = _split(_sdk(), CacheKind.ANDROID_SDK)
    assert {item.id: item.size for item in items} == {
        "system-images;android-35;google_apis;x86_64": 20700,
        "platforms;android-35": 10500,
        "build-tools;35.0.0": 5800,
    }
    assert {item.kind for item in items} == {CacheItemKind.ANDROID_PACKAGE}
    assert items[0].path == f"{SDK_ROOT}/system-images/android-35/google_apis/x86_64"


def test_sdk_never_offers_cmdline_tools_or_licenses() -> None:
    items, rest = _split(_sdk(), CacheKind.ANDROID_SDK)
    ids = " ".join(item.id for item in items)
    assert "cmdline-tools" not in ids
    assert "licenses" not in ids
    # their files (and the .temp leftovers) stay in the rest
    assert rest.unattributed == 600 + 3000 + 100 + 40 + 300


def test_sdk_sum_rule_items_plus_rest_is_the_size() -> None:
    listing = _sdk()
    items, rest = _split(listing, CacheKind.ANDROID_SDK)
    total = sum(item.size for item in items) + rest.shared + rest.unattributed
    assert total == regular_total(listing)


def test_sdk_folder_without_package_xml_is_not_an_item() -> None:
    listing = _sdk((d("extras"), f("extras/readme.txt", 10)))
    items, _ = _split(listing, CacheKind.ANDROID_SDK)
    assert "extras" not in {item.id for item in items}


def test_sdk_package_xml_that_is_a_link_does_not_make_a_package() -> None:
    listing = _sdk((d("ndk"), d("ndk/26.1"), ln("ndk/26.1/package.xml", "/etc/passwd")))
    items, _ = _split(listing, CacheKind.ANDROID_SDK)
    assert "ndk;26.1" not in {item.id for item in items}


def test_sdk_file_hard_linked_between_two_packages_is_shared() -> None:
    both = (
        f("platforms/android-35/same.bin", 4000, ino=777),
        f("build-tools/35.0.0/same.bin", 4000, ino=777),
    )
    listing = _sdk(both)
    items, rest = _split(listing, CacheKind.ANDROID_SDK)
    sizes = {item.id: item.size for item in items}
    assert sizes["platforms;android-35"] == 10500
    assert sizes["build-tools;35.0.0"] == 5800
    assert rest.shared == 4000


def test_sdk_empty_listing_gives_no_items() -> None:
    items, rest = items_for(
        kind=CacheKind.ANDROID_SDK, listing=TreeListing(root=SDK_ROOT, entries=()), size=0
    )
    assert items == ()
    assert (rest.shared, rest.unattributed) == (0, 0)


def _avd() -> TreeListing:
    entries = (
        d("Pixel_8.avd", ino=31),
        f("Pixel_8.avd/userdata.img", 8000),
        f("Pixel_8.avd/config.ini", 60),
        f("Pixel_8.ini", 100),
        d("Tablet.avd", ino=32),
        f("Tablet.avd/userdata.img", 3000),
        f("stray.ini", 50),
        d("loose"),
    )
    return TreeListing(root=AVD_ROOT, entries=entries)


def test_avd_item_is_the_device_folder_plus_its_ini() -> None:
    items, _ = _split(_avd(), CacheKind.ANDROID_AVD)
    pixel = next(item for item in items if item.id == "Pixel_8")
    assert pixel.size == 8000 + 60 + 100
    assert pixel.kind is CacheItemKind.ANDROID_AVD
    assert pixel.path == f"{AVD_ROOT}/Pixel_8.avd"
    assert (pixel.st_ino, pixel.st_dev) == (31, DEV)
    assert [(b.path, b.size) for b in pixel.blobs] == [("Pixel_8.ini", 100)]


def test_avd_without_ini_is_still_a_device_and_a_lone_ini_is_not() -> None:
    items, rest = _split(_avd(), CacheKind.ANDROID_AVD)
    assert {item.id: item.size for item in items} == {"Pixel_8": 8160, "Tablet": 3000}
    assert next(item for item in items if item.id == "Tablet").blobs == ()
    assert rest.unattributed == 50


def test_avd_sum_rule_items_plus_rest_is_the_size() -> None:
    listing = _avd()
    items, rest = _split(listing, CacheKind.ANDROID_AVD)
    assert sum(i.size for i in items) + rest.shared + rest.unattributed == regular_total(listing)


def test_a_package_folder_with_an_ambiguous_name_is_not_an_item() -> None:
    # sdkmanager would read "platforms;android-34" as the real platforms/android-34, and a
    # leading "-" as one of its options: such folders stay in the rest, never offered.
    odd = (
        d("platforms;android-34"),
        f("platforms;android-34/package.xml", 10),
        d("--package_file=x"),
        f("--package_file=x/package.xml", 10),
        d("extras"),
        d("extras/-google"),
        f("extras/-google/package.xml", 10),
    )
    ids = {item.id for item in _split(_sdk(extra=odd), CacheKind.ANDROID_SDK)[0]}
    assert "platforms;android-35" in ids
    assert ids.isdisjoint({"platforms;android-34", "--package_file=x", "extras;-google"})


def test_an_avd_whose_name_starts_with_a_dash_is_not_an_item() -> None:
    listing = TreeListing(
        root=AVD_ROOT,
        entries=(d("-n.avd", ino=33), f("-n.ini", 10), d("Ok.avd", ino=34), f("Ok.ini", 10)),
    )
    ids = {item.id for item in _split(listing, CacheKind.ANDROID_AVD)[0]}
    assert ids == {"Ok"}
