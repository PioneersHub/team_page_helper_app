import argparse  # noqa: I001
from team_page import log

from team_page.process import UpdateTeamPage


def main():
    parser = argparse.ArgumentParser(description="Update team page data.")
    parser.add_argument(
        "--mode",
        choices=["local", "full"],
        default="full",
        help="Specify the update mode: 'local' for local update only, 'full' for full update including making a PR to the website repo.",
    )
    args = parser.parse_args()

    updater = UpdateTeamPage()

    if args.mode == "local":
        updater.get_repo()
        data_bag = updater.create_databag()
        updater.save_json(data_bag)
        updater.save_yaml(data_bag)
        log.info("Local update completed.")
    elif args.mode == "full":
        updater.run_update()
        log.info("Full update completed.")


if __name__ == "__main__":
    main()
