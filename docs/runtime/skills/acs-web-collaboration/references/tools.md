# Web collaboration tool map

- read_profile confirms identity, Profiles and connection state.
- list_projects discovers authorized project_id values.
- load_project hydrates Root, Route, instruction and Source context.
- list_sources chooses filesystem or external repository access.
- list_files, search_files, read_file, read_source and read_diff provide bounded
  source reads when ACS owns the SourceBinding path.
- check_inbox and read_message recover durable collaboration state.
- list_evidence, list_reviews and submit_review support remote Review.

MCP server instructions expose the minimum startup rule. Skill metadata routes
the current question to the relevant knowledge module. References load only when
the question needs their detail.
