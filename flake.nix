{
  description = "Argo: macOS voice and AI assistant";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nixpkgs-darwin-legacy.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-darwin-legacy,
    }:
    let
      version = builtins.replaceStrings [ "\n" ] [ "" ] (builtins.readFile ./VERSION);
      targetSystems = [
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forEachSystem =
        f:
        builtins.listToAttrs (
          map (system: {
            name = system;
            value = f system;
          }) targetSystems
        );
      pkgsFor =
        system:
        if system == "x86_64-darwin" then
          nixpkgs-darwin-legacy.legacyPackages.${system}
        else
          nixpkgs.legacyPackages.${system};
      packageFor =
        system:
        let
          pkgs = pkgsFor system;
        in
        pkgs.writeShellApplication {
          name = "argo";
          runtimeInputs = [ pkgs.python313 ];
          text = ''
            set -euo pipefail
            src=${./.}
            case "''${1:-}" in
              ""|install|--install|build|--build)
                exec bash "$src/build.sh"
                ;;
              --check)
                python3 -c 'import pathlib, sys; compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], "exec")' "$src/argo.py"
                bash -n "$src/build.sh"
                bash -n "$src/install.sh"
                printf '%s\n' 'argo source checks passed'
                ;;
              --version)
                printf '%s\n' "argo ${version}"
                ;;
              --help|-h|help)
                cat <<'EOF'
            Argo launcher for macOS.

            Usage:
              argo              Install or update Argo.app
              argo --install    Install or update Argo.app
              argo --check      Run packaged source checks
              argo --version    Print the packaged version
              argo --help       Show this help

            Building requires macOS 26 or later and Apple's command line tools.
            Full use also requires Claude Code (with Claude or a custom server), Devin, or Pi.
            EOF
                ;;
              *)
                printf 'Unknown option: %s\n\n' "$1" >&2
                exec "$0" --help
                ;;
            esac
          '';
          meta = with pkgs.lib; {
            description = "Argo macOS app launcher";
            homepage = "https://github.com/panosadamop/argo-mac";
            license = licenses.mit;
            mainProgram = "argo";
            platforms = targetSystems;
          };
        };
    in
    {
      packages = forEachSystem (
        system:
        let
          argo = packageFor system;
        in
        {
          inherit argo;
          argo-mac = argo;
          source = argo;
          default = argo;
        }
      );

      apps = forEachSystem (
        system:
        let
          argo = self.packages.${system}.default;
          program = "${argo}/bin/argo";
          app = {
            type = "app";
            inherit program;
            inherit (argo) meta;
          };
        in
        {
          argo = app;
          argo-mac = app;
          default = app;
        }
      );

      checks = forEachSystem (system: {
        package = self.packages.${system}.default;
      });

      devShells = forEachSystem (system: {
        default =
          let
            pkgs = pkgsFor system;
          in
          pkgs.mkShell {
            packages = [
              pkgs.python313
              pkgs.act
            ];
            shellHook = ''
              echo "Argo development shell. Building the app requires Apple's command line tools."
            '';
          };
      });

      formatter = forEachSystem (system: (pkgsFor system).nixfmt);
    };
}
