# Custom PyInstaller hook for Streamlit.
# The auto-generated hook sometimes misses static assets and runtime modules;
# this file supplements it.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("streamlit", includes=["**/*"])
hiddenimports = collect_submodules("streamlit")
