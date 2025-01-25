"""
Create the data for the team page into a JSON located in './databags/team.json'
The info is collected via a Google Form and read from a Google Sheet.
"""

import contextlib
import shutil
from pathlib import Path

import requests
from git import Repo
from pydantic import ValidationError
from pytanis import GSheetsClient

from team_page import CONFIG, GITHUB_TOKEN, TEAM_SHEET_ID, TEAM_WORKSHEET_NAME, log
from team_page.models import Committee, TeamDataBag, TeamMember


class UpdateTeamPage:

    def __init__(self):

        self.repo = None
        self.gsheets_client = GSheetsClient()
        self.gsheet_df = None
        # standard paths
        self.local_repo_path = Path(__file__).parents[1] / CONFIG["local_repo_path"]
        self.image_dir = self.local_repo_path / CONFIG["team_images"]
        self.databag_dir = self.local_repo_path / "databags"
        self.databag = self.databag_dir / "team.json"
        # set up
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.databag_dir.mkdir(parents=True, exist_ok=True)

    def read_gsheet(self):
        gsheet_df = self.gsheets_client.gsheet_as_df(TEAM_SHEET_ID, TEAM_WORKSHEET_NAME)
        log.info("Downloaded Google Sheet")
        return gsheet_df


    def get_repo(self):
        if self.local_repo_path.exists():
            shutil.rmtree(self.local_repo_path) 
        log.info("Cloning repository...")
        self.repo = Repo.clone_from(CONFIG["git_repo_url"].replace("https://", f"https://{GITHUB_TOKEN}@"), self.local_repo_path)

        if CONFIG["branch_name"] in self.repo.heads:
            self.repo.git.checkout(CONFIG["branch_name"])
        else:
            self.repo.git.checkout("-b", CONFIG["branch_name"])

    def sheet_to_json(self):
        self.gsheet_df = self.get_gsheet()
        records = self.gsheet_df.rename(columns=CONFIG["member"]).fillna("").to_dict(orient="records")
        members = {x: [] for x in {c.get("committee") for c in records if c.get("committee")}}

        for record in records:
            if record["ignore"].casefold() != "yes":
                continue
            record["role"] = "Chair" if record["chair"].casefold() == "yes" else ""
            try:
                member = TeamMember(**record)
            except ValidationError as e:
                log.error(f"Failed to create TeamMember: {e}")
                continue
            self.download_member_image(member)
            members[record.get("committee", "other")].append(member)


        committees = [Committee(name=k, members=v) for k, v in members.items()]
        log.info("Created committees")
        committees = self.sort_committees(committees)
        # noinspection PyTypeChecker
        data_bag = TeamDataBag(
            team_images=CONFIG["team_images"],
            default_image=CONFIG["default_image"],
            types=committees,
        )
        log.info("Created TeamDataBag")
        return data_bag

    @classmethod
    def sort_committees(cls, committees):
        """Display committees in a particular order on the website."""
        committees = sorted(
            [c for c in committees if c.name in CONFIG["sort_order"]],
            key=lambda c: CONFIG["sort_order"].index(c.name),
        ) + [c for c in committees if c.name not in CONFIG["sort_order"]]
        log.info("Sorted committees")
        return committees

    def download_member_image(self, member: TeamMember):
        if not member.image_file:
            return
        with contextlib.suppress(Exception):
            if (self.image_dir / member.image_file.path.split("/")[-1]).exists():
                # avoid repeated image updates
                return
        normalized_name = self.normalized_member_name(member.name)
        if normalized_name in self.image_dir.rglob("*"):
            log.info(f"Image for {member.name} already exists, remove from website repofirst to update.")
            return

        url = member.image_file
        try:
            # Step 1: Fetch Content-Type from the URL
            try:
                response = requests.head(url, allow_redirects=True)
                response.raise_for_status()
            except requests.RequestException as e:
                message = f"Failed to fetch URL headers: {e}"
                log.error(message)
                raise ValueError(message) from e

            content_type = response.headers.get("Content-Type").strip()
            if not content_type or not content_type.startswith("image/"):
                message = f"URL does not point to a valid image: {url}"
                log.error(message)
                raise ValueError(message)

            # Send a GET request to the URL
            response = requests.get(member.image_file, stream=True)
            response.raise_for_status()  # Raise an error for HTTP codes >= 400

            member_image = self.__init__image_dir / f"{normalized_name}.{content_type.split('/')[-1]}"
            # Write the image content to a file
            with open(member_image, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
                self.repo.git.add(str(member_image))

            log.info("Image downloaded successfully and saved")

        except requests.exceptions.RequestException as e:
            log.info(f"Failed to download the image: {e}")

    def normalized_member_name(self, name: str) -> str:
        return name.replace(" ", "_").lower()

    def save_json(self, data_bag: TeamDataBag):
        with self.databag.open("w") as f:
            f.write(data_bag.model_dump_json(indent=4))
        log.info("Created data_bag json")

    def commit_changes(self):
        self.repo.index.commit("Update team data")
        try:
            origin = self.repo.remote(name="origin")
            branch_name = self.active_branch.name

            # Check if the branch has an upstream set
            tracking_branch = self.active_branch.tracking_branch()
            if not tracking_branch:
                # Set the upstream branch if it doesn't exist
                log.info(f"Setting upstream branch for '{branch_name}'...")
                self.repo.git.push("--set-upstream", "origin", branch_name)
            else:
                log.info(f"Upstream branch already set: {tracking_branch.name}")

            # Push changes
            log.info("Pushing changes to remote repository...")
            origin.push()

        except Exception as e:
            log.error(f"Failed to commit and push changes: {e}")
            raise

    def pull_request(self):
        # Step 5: Create a pull request
        log.info("Creating a pull request...")
        api_url = f"https://api.github.com/repos/{CONFIG["repo_owner"]}/{CONFIG["repo_name"]}/pulls"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        payload = {
            "title": "Team page auto-update",
            "head": CONFIG["branch_name"],
            "base": "main",  # Replace with your default branch name if different
            "body": "This pull request adds extra data to the repository.",
        }

        response = requests.post(api_url, headers=headers, json=payload)

        if response.status_code == 201:
            log.info("Pull request created successfully!")
        else:
            log.info("Failed to create pull request:", response.status_code)
            log.info(response.json())

    def run_update(self):
        self.get_repo()
        new_data_bag = self.sheet_to_json()
        self.save_json(new_data_bag)
        self.commit_changes()
        self.pull_request()
