{
  description = "Cascade - a smart task scheduler";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    flake-utils.url = "github:numtide/flake-utils";

    git-hooks.url = "github:cachix/git-hooks.nix";
  };

  outputs =
    {
      self,
      nixpkgs,
      uv2nix,
      pyproject-nix,
      pyproject-build-systems,
      flake-utils,
      git-hooks,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        inherit (nixpkgs) lib;
        pkgs = nixpkgs.legacyPackages.${system};

        python = pkgs.python312;

        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

        uvOverlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        pyprojectOverrides = _final: _prev: {
          # Implement build fixups here.
          # Note that uv2nix is _not_ using Nixpkgs buildPythonPackage.
          # It's using https://pyproject-nix.github.io/pyproject.nix/build.html
        };

        pythonSet =
          # Use base package set from pyproject.nix builders
          (pkgs.callPackage pyproject-nix.build.packages {
            inherit python;
          }).overrideScope
            (
              lib.composeManyExtensions [
                pyproject-build-systems.overlays.default
                uvOverlay
                pyprojectOverrides
              ]
            );
      in
      {
        packages = rec {
          venv = pythonSet.mkVirtualEnv "cascade-env" workspace.deps.default;
          default = venv;
        };

        apps = rec {
          cascade-bin = {
            type = "app";
            program = "${self.packages.x86_64-linux.default}/bin/cascade";
          };
          default = cascade-bin;
        };

        devShells = {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.uv
            ];
            env = {
              UV_PYTHON_DOWNLOADS = "never";
              UV_PYTHON = python.interpreter;
            }
            // lib.optionalAttrs pkgs.stdenv.isLinux {
              LD_LIBRARY_PATH = lib.makeLibraryPath pkgs.pythonManylinuxPackages.manylinux1;
            };
            shellHook = self.checks.${system}.pre-commit-check.shellHook + ''
              unset PYTHONPATH
              export PATH="$HOME/.local/bin:$PATH"
            '';
          };
        };

        checks = {
          pre-commit-check = git-hooks.lib.${system}.run {
            src = ./.;
            hooks = {
              nixfmt-rfc-style.enable = true;
              black.enable = true;
            };
          };
        };
      }
    );
}
