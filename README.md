## Sheets

Effortless synchronization between your online SpreadSheet Apps & ERPNext


### Details

1. Make a service account for auth of Sheets (ref: https://docs.gspread.org/en/latest/oauth2.html#for-bots-using-service-account)
2. Setup spreadsheet document
  - setup worksheet -> doctype mapping
  - setup sync frequency
- app maintains row idx of worksheet to maintain last imported row

#### Data import details

- import job will fetch a subsection of the spreadsheet [counter:latest_idx] and store it as a temporary csv which will be used to create Data Import documents

- Saving "SpreadSheet" document will trigger generation/updation of "Scheduled Job Type" documents / call internally defined function through Server Script defined automatically by this app. Maintain links to Server Script & Scheduled Job in doc

Use Data Import as view for the results of the import - new custom field(s) ("Generated By")

#### License

Copyright © 2023, Gavin D'souza [gavin18d@gmail.com].

ToolBox is released under "GNU GPLv3" License. Refer to [LICENSE](LICENSE) for full information.
