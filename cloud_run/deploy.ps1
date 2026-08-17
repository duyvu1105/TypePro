param(
    [string]$RunId = "production-v1",
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$Config = Get-Content -LiteralPath "$PSScriptRoot\config.json" | ConvertFrom-Json
$Project = $Config.project_id
$Region = $Config.region
$Bucket = $Config.bucket
$ServiceAccount = "$($Config.service_account)@$Project.iam.gserviceaccount.com"
$Image = "$Region-docker.pkg.dev/$Project/$($Config.artifact_repository)/typepro-builder:$RunId"
$ProjectNumber = gcloud projects describe $Project --format "value(projectNumber)"
$BuildServiceAccount = "$ProjectNumber-compute@developer.gserviceaccount.com"
$WorkflowsServiceAgent = "service-$ProjectNumber@gcp-sa-workflows.iam.gserviceaccount.com"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com workflows.googleapis.com --project $Project
gcloud artifacts repositories describe $Config.artifact_repository --location $Region --project $Project 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud artifacts repositories create $Config.artifact_repository --repository-format docker --location $Region --project $Project
}
gcloud storage buckets describe "gs://$Bucket" --project $Project 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud storage buckets create "gs://$Bucket" --project $Project --location $Region --uniform-bucket-level-access
}
gcloud iam service-accounts describe $ServiceAccount --project $Project 2>$null
if ($LASTEXITCODE -ne 0) {
gcloud iam service-accounts create $Config.service_account --project $Project --display-name "TypePro Cloud Run builder"
}
gcloud iam service-accounts add-iam-policy-binding $ServiceAccount --project $Project --member "serviceAccount:$WorkflowsServiceAgent" --role roles/iam.serviceAccountTokenCreator
gcloud storage buckets add-iam-policy-binding "gs://$Bucket" --member "serviceAccount:$ServiceAccount" --role roles/storage.objectAdmin
gcloud artifacts repositories add-iam-policy-binding $Config.artifact_repository --location $Region --project $Project --member "serviceAccount:$BuildServiceAccount" --role roles/artifactregistry.writer
gcloud projects add-iam-policy-binding $Project --member "serviceAccount:$ServiceAccount" --role roles/run.viewer --condition None

gcloud builds submit --project $Project --region $Region --config "$PSScriptRoot\cloudbuild.yaml" --substitutions "_IMAGE=$Image" "$PSScriptRoot\.."
gcloud run jobs deploy $Config.shard_job --project $Project --region $Region --image $Image --service-account $ServiceAccount --tasks 10 --parallelism 2 --cpu 4 --memory 16Gi --task-timeout 24h --max-retries 2 --args "--mode,shard" --set-env-vars "TYPEPRO_BUCKET=$Bucket,TYPEPRO_RUN_ID=$RunId"
gcloud run jobs deploy $Config.finalize_job --project $Project --region $Region --image $Image --service-account $ServiceAccount --tasks 1 --parallelism 1 --cpu 4 --memory 16Gi --task-timeout 6h --max-retries 1 --args "--mode,finalize" --set-env-vars "TYPEPRO_BUCKET=$Bucket,TYPEPRO_RUN_ID=$RunId"
gcloud run jobs add-iam-policy-binding $Config.shard_job --project $Project --region $Region --member "serviceAccount:$ServiceAccount" --role roles/run.invoker
gcloud run jobs add-iam-policy-binding $Config.finalize_job --project $Project --region $Region --member "serviceAccount:$ServiceAccount" --role roles/run.invoker
gcloud workflows deploy $Config.workflow --project $Project --location $Region --source "$PSScriptRoot\workflow.yaml" --service-account $ServiceAccount

if ($Execute) {
    gcloud workflows run $Config.workflow --project $Project --location $Region
}
