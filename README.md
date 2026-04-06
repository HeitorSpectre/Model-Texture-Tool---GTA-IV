# Model Texture Tool - GTA IV

`Model Texture Tool - GTA IV` is a tool for opening and editing embedded textures from GTA IV model files on the following platforms:

- `PC` with `.wdr` files  
- `PS3` with `.cdr` files  
- `Xbox 360` with `.xdr` files  

# Test

Xbox 360:

<img width="958" height="519" alt="image" src="https://github.com/user-attachments/assets/40690c51-2180-42a5-8b62-ed41f5b6fe3c" />

PS3:

<img width="959" height="569" alt="image" src="https://github.com/user-attachments/assets/7ffc6659-4451-4baa-a119-0f6598a2fb3d" />

PC:

<img width="957" height="627" alt="image" src="https://github.com/user-attachments/assets/302ebcdf-c6b6-4ee4-abc8-c0ec6d31523c" />

This version of the project was organized to use the main tool in `Python`, while the `CSharp` folder is used to compile the DLLs and dependencies that the Python script needs to run.

## Project structure

- `CSharp/`  
  Responsible for compiling the backend DLLs and copying everything to the `Python/vendor` folder.  
- `Python/`  
  Main part of the tool, including interface, backend, and option to generate an `.exe`.

## Step-by-step tutorial

### 1. Open the `CSharp` folder

Go into the `CSharp` folder.

There you have 2 ways to prepare the backend:

- run `build_python_vendor.bat`  
- or open `Model Texture Tool.sln` in Visual Studio and build in `Release`  

This step compiles the required DLLs for the Python tool and copies the files to `Python/vendor`.

Note:

- the old C# interface remains only as reference in `CSharp/Legacy WinForms Tool`  
- the main tool is now the Python version  

### 2. Go to the `Python` folder

After compiling the DLLs in the previous step, open the `Python` folder.

There you can choose between:

- running the Python script  
- or compiling the tool into an `.exe`  

## How to run the Python script

### 1. Install a standard Python

Use a normal `Python 3.11+` for Windows, with `tkinter` support.

### 2. Install the dependencies

In the terminal, inside the `Python` folder, run:

```bat
pip install -r requirements.txt
```

### 3. Run the tool

You can open the tool with:

```bat
run_tool.bat
```

or:

```bat
python main.py
```

## How to compile the Python tool into EXE

### 1. Go into the `Python` folder

### 2. Run the file:

```bat
build_exe.bat
```

This `.bat` installs everything needed for the build and generates the compiled version of the tool.

Expected output:

```text
Python\dist\Model Texture Tool.exe
```

## Quick summary

1. Open `CSharp`
2. Run `build_python_vendor.bat` or build `Model Texture Tool.sln`
3. Open `Python`
4. Choose between:

   * running `run_tool.bat` / `python main.py`
   * or running `build_exe.bat` to generate the `.exe`

---------------

## Credits

* HeitorSpectre
* Giga
* TicoDoido
* GameLab Traduções

## Special Thanks
* RAGE Console Texture Editor
* SparkIV
* IVPCXbox
