# qualcoder-importer
Import Google Sheets codebook into QualCoder

Import a csv with the following values: 
Category	Sub Category	Code	Definition
Leave blank to start a new (subcategory/category). 

## Usage

```bash
python codebook_to_qdc.py Codebook.csv output.qdc
```

Optionally, pass in `--seed ##` to generate different color. 

## To Import to QualCoder

Launch QualCoder, select `project`, `import`, `REFI-QDA Codebook Import`, and select the generated fie. 

## Known Issues

QualCoder would have degraded performance if a large amount of code is imported. I am not sure if this is an issue with my setup, but it should be a QualCoder issue rather than this script. 
