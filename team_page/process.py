"""
Create the data for the team page into a JSON located in './databags/team.json'
The info is collected via a Google Form and read from a Google Sheet.
"""

import contextlib
import shutil
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from git import GitCommandError, Repo
from pydantic import AnyHttpUrl, ValidationError
from pytanis import GSheetsClient

from team_page import CONFIG, TEAM_SHEET_ID, TEAM_WORKSHEET_NAME, WEBSITE_REPOSITORY_TOKEN, log
from team_page.models import Committee, TeamDataBag, TeamMember
from team_page.utils import obfuscate_name


class UpdateTeamPage:
    def __init__(self):
        self.repo = None
        self.gsheets_client = GSheetsClient()
        self.gsheet_df = None
        self.changes_to_push = False
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
        self.repo = Repo.clone_from(
            CONFIG["git_repo_url"].replace("https://", f"https://{WEBSITE_REPOSITORY_TOKEN}@"), self.local_repo_path
        )
        self.repo.git.fetch("--all")
        if CONFIG["branch_name"] in self.repo.heads:
            self.repo.git.checkout(CONFIG["branch_name"])
            log.info(f"Checked out existing branch {CONFIG['branch_name']}")
            log.info(f"Pulling latest changes from remote branch {CONFIG['branch_name']}...")
            self.repo.git.pull("origin", CONFIG["branch_name"], "--rebase")
            log.info(f"Pulled latest changes for branch {CONFIG['branch_name']}")
        else:
            self.repo.git.checkout("-b", CONFIG["branch_name"])
            log.info(f"Created and checked out new branch {CONFIG['branch_name']}")

    def create_databag(self):
        log.info("Converting Google Sheet to JSON")
        self.gsheet_df = self.read_gsheet()
        log.info("Read Google Sheet")
        records = self.gsheet_df.rename(columns=CONFIG["member"]).fillna("").to_dict(orient="records")
        members = {x: [] for x in {c.get("committee") for c in records if c.get("committee")}}
        log.info(f"Found {len(records)} members in the Google Sheet")

        log.info("Creating TeamMembers")
        for i, record in enumerate(records, 1):
            log.info(f"Processing record {i}/{len(records)} {obfuscate_name(record['name'])}")
            if record["ignore"].casefold() != "yes":
                continue
            record["role"] = "Chair" if record["chair"].casefold() == "yes" else ""
            try:
                member = TeamMember(**record)
                try:
                    image_name = self.download_member_image(member)
                except Exception:
                    image_name = None
                # data bag should contain only the image file name
                member.image_url = None
                member.image_name = image_name
                members[record.get("committee", "other")].append(member)
            except (ValidationError, KeyError, ValueError) as e:
                log.error(f"Failed to create TeamMember: {e}")
                continue

        log.info("Created TeamMembers, creating Committees")
        committees = [Committee(name=k, members=v) for k, v in members.items()]
        log.info("Created Committees")
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
        if not member.image_url:
            return
        with contextlib.suppress(Exception):
            if (self.image_dir / member.image_url.path.split("/")[-1]).exists():
                # avoid repeated image updates
                return
        normalized_name = self.normalized_member_name(member.name)
        image_in_place = [x for x in {x.name.casefold() for x in self.image_dir.rglob("*")} if normalized_name in x]
        if image_in_place:
            log.info(
                f"Image for {obfuscate_name(member.name)} already exists, remove from website repo first to update."
            )
            return image_in_place[0]

        url = member.image_url
        return self.download(url, member, normalized_name)

    @classmethod
    def validate_content_type(cls, response) -> str:
        content_type = response.headers.get("Content-Type").strip()
        if not content_type or not content_type.startswith("image/"):
            message = f"URL does not point to a valid image: {content_type}"
            log.error(message)
            raise ValueError(message)
        return content_type.split("/")[-1]

    def download(self, url: AnyHttpUrl, member: TeamMember, normalized_name: str):
        try:
            if url.host == "drive.google.com":
                # needs to be downloaded via session
                parsed_url = urlparse(str(url))
                gid = parse_qs(parsed_url.query)["id"][0]
                session = requests.Session()
                response = session.get("https://docs.google.com/uc?export=download", params={"id": gid}, stream=True)
                ext = self.validate_content_type(response)
            else:
                url = str(member.image_url)
                # Step 1: Fetch Content-Type from the URL
                try:
                    response = requests.head(url, allow_redirects=True)
                    response.raise_for_status()
                except requests.RequestException as e:
                    message = f"Failed to fetch URL headers: {e}"
                    log.error(message)
                    raise ValueError(message) from e

                ext = self.validate_content_type(response)
                response = requests.get(url, stream=True)
                response.raise_for_status()  # Raise an error for HTTP codes >= 400

            member_image = self.image_dir / f"{normalized_name}.{ext}"
            # Write the image content to a file
            with open(member_image, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
                self.repo.git.add(str(member_image))
            log.info(f"Image {obfuscate_name(member.name)} downloaded successfully and saved")
            return member_image.name

        except requests.exceptions.RequestException as e:
            log.info(f"Failed to download the image: {e}")

    def normalized_member_name(self, name: str) -> str:
        return name.replace(" ", "_").casefold()

    def save_json(self, data_bag: TeamDataBag):
        with self.databag.open("w") as f:
            f.write(data_bag.model_dump_json(indent=4))
        log.info("Created data_bag json")

    def apply_changes(self):
        """Compare the local branch and the remote branch if there is any difference to push, the remote branch is origin/main."""
        try:
            # Check for changes
            if self.repo.is_dirty(untracked_files=True):
                log.info("Changes detected, committing changes...")
                self.repo.git.add(A=True)
                self.repo.index.commit("Update team page data")
                self.changes_to_push = True
            else:
                log.info("No changes detected in the repository.")

            # Check if there are any differences between the local and remote branches
            remote_branch = self.repo.remotes.origin.refs.main
            local_branch = self.repo.heads[CONFIG["branch_name"]]

            if local_branch.commit != remote_branch.commit:
                log.info("Differences detected between local and remote branches.")
                self.changes_to_push = True
            else:
                log.info("No differences detected between local and remote branches.")
                self.changes_to_push = False

            # Push changes to the remote repository if there are any changes to push
            if self.changes_to_push:
                log.info(f"Pushing changes to remote branch {CONFIG['branch_name']}...")
                self.repo.git.push("origin", CONFIG["branch_name"], "--force-with-lease")
                log.info("Changes pushed successfully.")

        except Exception as e:
            log.error(f"Failed to commit and push changes: {e}")
            raise

    def pull_request(self):
        if not self.changes_to_push:
            log.info("No PR to make. Exiting...")
            return
        # Step 5: Create a pull request
        # Check if a pull request already exists for this branch
        log.info("Checking if a pull request already exists for this branch...")
        pr_url = f"https://api.github.com/repos/{CONFIG['repo_owner']}/{CONFIG['repo_name']}/pulls"
        headers = {
            "Authorization": f"Bearer {WEBSITE_REPOSITORY_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        params = {
            "head": f"{CONFIG['repo_owner']}:{CONFIG['branch_name']}",
            "base": "main",
        }
        response = requests.get(pr_url, headers=headers, params=params)

        if response.status_code == HTTPStatus.OK:
            existing_prs = response.json()
            if existing_prs:
                log.info("A pull request already exists for this branch. Exiting...")
                return
        else:
            log.error(f"Failed to check for existing pull requests: {response.status_code}")
            log.error(response.json())
        log.info("Creating a pull request...")
        api_url = f"https://api.github.com/repos/{CONFIG['repo_owner']}/{CONFIG['repo_name']}/pulls"
        payload = {
            "title": "Team page auto-update",
            "head": CONFIG["branch_name"],
            "base": "main",
            "body": "This pull request adds extra data to the repository.",
        }

        response = requests.post(api_url, headers=headers, json=payload)

        if response.status_code == HTTPStatus.CREATED:
            log.info("Pull request created successfully!")
            pr = response.json()
            reviewers_url = pr["url"] + "/requested_reviewers"
            reviewers_payload = {"reviewers": CONFIG["pr_reviewers"]}
            reviewers_response = requests.post(reviewers_url, headers=headers, json=reviewers_payload)

            if reviewers_response.status_code == HTTPStatus.CREATED:
                log.info("Pull request assigned successfully!")
            else:
                log.warn(f"Failed to assign pull request: {reviewers_response.status_code}")
                log.warn(reviewers_response.json())
        else:
            log.info("Failed to create pull request:", response.status_code)
            log.info(response.json())

    def check_for_changes(self):
        try:
            # Fetch the latest changes from the remote
            origin = self.repo.remote(name="origin")
            origin.fetch()

            # Get the current branch and its tracking branch
            local_branch = self.repo.active_branch
            tracking_branch = local_branch.tracking_branch()
            log.info(f"Local branch: {local_branch.name}")
            log.info(f"Tracking branch: {tracking_branch.name if tracking_branch else None}")

            if not tracking_branch:
                raise ValueError(f"Local branch '{local_branch}' has no upstream branch.")

            # Compare local and remote branch commits
            local_commit = self.repo.commit(local_branch)
            remote_commit = self.repo.commit(tracking_branch)

            if local_commit != remote_commit or not self.remote_exists:
                log.info("Changes detected: Local and remote branches differ.")
                self.changes_to_push = True
            else:
                log.info("No changes detected: Local and remote branches are in sync.")

        except GitCommandError as e:
            log.info(f"Git command failed: {e}")
        except Exception as e:
            log.info(f"Error: {e}")

    def run_update(self):
        self.get_repo()
        new_data_bag = self.create_databag()
        self.save_json(new_data_bag)
        self.apply_changes()
        # self.check_for_changes()
        self.pull_request()
