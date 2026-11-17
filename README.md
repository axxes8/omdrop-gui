# Omdrop desktop

A small desktop GUI for the installed Owly AirDrop command-line client.

## Download

GitHub Actions builds an x86-64 AppImage on each push. Open the latest successful
**Build AppImage** run under the repository's **Actions** tab and download the
`Omdrop-x86_64-AppImage` artifact. Extract the downloaded ZIP before running it.
GitHub requires you to sign in to download workflow artifacts; artifacts expire
according to the repository's retention settings.

## Requirements

- `owly` and its `owlyd` service, installed through `omdrop-owl`
- Python 3 and PySide6 (`pyside6` on CachyOS/Arch), if running from source
- A supported Wi-Fi adapter; run `owly doctor` to check it

## Run

For the AppImage, make it executable once, then run it:

```sh
chmod +x Omdrop-x86_64.AppImage
./Omdrop-x86_64.AppImage
```

The AppImage bundles Python and PySide6, but still requires the installed `owly`
command and `owlyd` service. The GitHub build runs on Ubuntu 24.04 x86-64 and
requires a compatible Linux system. AppImages do not automatically appear in the
app menu.

Alternatively, run from source:

```sh
python3 omdrop_gui.py
```

Enable the radio, set the receiving device's AirDrop to **Everyone for 10 minutes**,
find devices, select one, choose a file, and send it. Accept the transfer on the
receiving device. Disable the radio when finished, or close the window.

Owly may temporarily disconnect Wi-Fi on some adapters while its radio is
enabled. If the radio or a transfer fails, check the activity log and run
`owly doctor`. The app uses `owly browse`'s text output, as provided by Owly
0.4.3; its output format may change in future versions.
