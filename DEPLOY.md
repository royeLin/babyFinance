# How to Deploy BabyFinance to Google Cloud Run

Since you don't have the Google Cloud CLI (`gcloud`) installed locally, the easiest way is to use **Google Cloud Shell**. It runs in your browser and has all the tools pre-installed.

## Step 1: Open Google Cloud Shell
1.  Go to [console.cloud.google.com](https://console.cloud.google.com).
2.  Select your project (or create one).
3.  Click the **Activate Cloud Shell** icon ( >_ ) in the top right toolbar.

## Step 2: Upload Your Code
1.  In the Cloud Shell terminal window, click the **Three Dots** icon > **Upload**.
2.  Upload your entire `babyFinance` folder (or zip it first and upload the zip, then unzip with `unzip filename.zip`).

## Step 3: Configure Environment
In Cloud Shell, navigate to your project folder:
```bash
cd babyFinance
```

You need to prepare the Firebase credentials string for the environment variable. Run this command to flatten your JSON key into a single line (assuming you uploaded the JSON key file):
```bash
export GOOGLE_APPLICATION_CREDENTIALS_CONTENT=$(cat babyfinace-firebase-adminsdk-*.json | tr -d '\n')
```

## Step 4: Deploy
Run the following command to build and deploy your app. Replace the placeholders with your actual keys (or set them in the Console later).

```bash
gcloud run deploy babyfinance \
  --source . \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars CHANNEL_SECRET="YOUR_CHANNEL_SECRET" \
  --set-env-vars CHANNEL_ACCESS_TOKEN="YOUR_ACCESS_TOKEN" \
  --set-env-vars GEMINI_API_KEY="YOUR_GEMINI_KEY" \
  --set-env-vars FIREBASE_CREDENTIALS_JSON="$GOOGLE_APPLICATION_CREDENTIALS_CONTENT"
```
*Note: You can choose a different region, e.g., `us-central1`. `asia-northeast1` is Tokyo.*

## Step 5: Webhook URL
Once deployed, Cloud Run will give you a Service URL (e.g., `https://babyfinance-xc72...a.run.app`).
1.  Copy this URL.
2.  Go to the **LINE Developers Console**.
3.  Update your Webhook URL to: `<YOUR_CLOUD_RUN_URL>/callback`
4.  Verify and Save.

## Troubleshooting
If the command fails due to large credentials, you can also deploy first without env vars, then go to the **Cloud Run UI** > **Edit & Deploy New Revision** > **Variables** and paste the values there manually.
