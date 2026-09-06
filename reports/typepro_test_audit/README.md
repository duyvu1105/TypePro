# Python test project provenance

`projects.txt` and `projects.csv` were extracted from
`RQ Results/RQ1&RQ2/Results/CodeT5P_out.json` using the `repos/owner/repository/`
prefix of each sample's `file` field. The artifact has 11,029 samples from 103
repository identifiers, including 2,269 arguments, 958 returns and 7,802 local
variables. CodeT5, TypeGen, Tiger and UnixCoder contain the same multiset of
`(file, loc, name, scope, gttype)` identities. The upstream TypeGen output at
https://github.com/umxadmin/TypePro was also checked against these identities.

The paper describes 100 projects; the published artifacts contain 103. Of
these, 63 have argument/return annotations, and 40 have only variable
annotations **in these artifacts**, not necessarily in their source code.
`build_coverage.json` compares this list with the TypeGen release and locally
reconstructed metadata using seed 13, built-ins and returns included. This
metadata audit is not proof of successful slicing on Kaggle.

The merge treats this as a preferred list. After preprocessing, it retains
available projects and fills to exactly 100 using other processed projects in
deterministic hash order. The authoritative selected list and replacement audit
are published with the Dataset as `test_projects.txt` and `test_split_audit.json`.
