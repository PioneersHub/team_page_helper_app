# Update Team Page

Helper application to add the team members to the website.

## Process

Overview of the process:

1. Retrieve data from a Google Sheet. This Google Sheets stores data collected via a Google Form (team self sign-up)
2. Clone local copy of the website
3. Update all information in databags/team.json from which the website generates the team page from
4. Download images of team members via link provided in Google Sheet
5. Comit files
6. Push to website repo
7. Make PR in website repo


## Requirements

1. Pytanis set up for Google Sheets, [see](https://pioneershub.github.io/pytanis/latest/usage/installation/)
2. Access to the Google Sheet with the team info
3. Read, write and PR access to the website repo with personal token

 ## Set-Up & Configugation

 Add to a local `.env`file:
```text
TEAM_SHEET_ID = "put the team sheet id here"
TEAM_WORKSHEET_NAME = "put the worksheet name here"
GITHUB_TOKEN = "put the github token to access the website repo here"
```

Check `config.