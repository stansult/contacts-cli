# Google setup

Configure Google API access and authorize the CLI to use your account. These steps cover setup with
a personal Google account.

## 1. Create a project

1. Open [Create a Google Cloud project](https://console.cloud.google.com/projectcreate).
2. Enter **Contacts CLI** as the project name.
3. Select **No organization** for the parent resource.
4. Click **Create**, then select **Contacts CLI** in the project selector at the top of the page.
   Keep that project selected when opening the links below.

## 2. Enable the APIs

1. Open **[APIs & Services](https://console.cloud.google.com/apis) → [Library](https://console.cloud.google.com/apis/library)**.
2. Open [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and click **Enable**.
3. Open [Google People API](https://console.cloud.google.com/apis/library/people.googleapis.com) and click **Enable**.

See Google's [API enablement instructions](https://developers.google.com/workspace/guides/enable-apis).

## 3. Configure consent and test access

1. Open [Google Auth Platform](https://console.cloud.google.com/auth) → [Branding](https://console.cloud.google.com/auth/branding) and click **Get Started**.
If setup is already complete, edit the settings in [Branding](https://console.cloud.google.com/auth/branding), [Audience](https://console.cloud.google.com/auth/audience), and [Data Access](https://console.cloud.google.com/auth/scopes) instead.
2. Set the app name to **Contacts CLI** and select your email as the support email. Click **Next**.
3. Choose **External** as the audience and click **Next**.
4. Enter your email under **Contact Information** and click **Next**.
5. Review the policy, accept it if you agree, then click **Continue → Create**.
6. Open [Audience](https://console.cloud.google.com/auth/audience). Keep the app in **Testing** for this setup.
7. Under **Test users**, click **Add users**, enter the Google account that owns your Gmail label
   and contact, and save.
8. Open [Data Access](https://console.cloud.google.com/auth/scopes) and click **Add or Remove Scopes**. Scroll down to **Manually add scopes**,
   and paste the following scopes, one per line:

   ```text
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/contacts
   ```

9. Click **Add to table**, then **Update**, then **Save** on the Data Access page.

See Google's [consent-screen instructions](https://developers.google.com/workspace/guides/configure-oauth-consent).

## 4. Create and download the client file

1. Open [Google Auth Platform](https://console.cloud.google.com/auth) → [Clients](https://console.cloud.google.com/auth/clients) and click **[Create Client](https://console.cloud.google.com/auth/clients/create)**.
2. Choose **Desktop app** as the application type.
3. Name the client **Contacts CLI**. Leave **Use this client for an AI-powered agent** unchecked,
   then click **Create**.
4. In your terminal, create the folder where you'll save the client file:

   ```sh
   mkdir -p "$HOME/.config/contacts-cli"
   ```

5. Download the client's JSON configuration
   - Save it as `~/.config/contacts-cli/credentials.json`.
   - If your browser automatically saves it to **Downloads**, move it to
   `~/.config/contacts-cli/` and rename it `credentials.json`.

The client file must exist before browser authorization can start.
See Google's [OAuth client creation instructions](https://developers.google.com/workspace/guides/create-credentials#desktop-app).

## 5. Authorize your account

From the checkout, run:

```sh
./contacts-cli authorize
```

The command opens your default browser. Select the account added as a test user, review the
requested permissions, and grant access. Complete this within five minutes while the terminal
command is running. The command reports **Authorization saved** when it succeeds.
If you do not finish within five minutes, the command reports an authorization timeout.
Run the command again to start a new attempt.

During sign-in, expect **Google hasn’t verified this app** for this personal, unverified setup.
Confirm that the app is the **Contacts CLI** client you created, then choose **Continue** to proceed.
If the warning shows **Advanced** instead, open it and select **Go to Contacts CLI (unsafe)**.
Google permits this flow for [personal-use apps](https://support.google.com/cloud/answer/13464323?hl=en) without verification.

For timeout testing, see the [testing guide](testing.md#authorization-timeout-testing).

For a client file stored elsewhere:

```sh
./contacts-cli authorize --credentials "/path/to/client.json"
```

To open the printed authorization URL manually:

```sh
./contacts-cli authorize --no-browser
```

After authorization, follow the [preview instructions](../README.md#sender-sync-preview-and-apply). Replace the example label and contact URL
with your own values.

## Permissions, tokens, and repeat authorization

The requested scopes are `gmail.readonly` and `contacts` (with Google's
`https://www.googleapis.com/auth/` prefix). Gmail read-only access permits reading messages,
including bodies, but no mail changes. The CLI requests only headers and labels; sender search
requires this permission. Contacts permission
allows writes across the account; Google does not offer a scope restricted to the selected contact.
The CLI writes contacts only after interactive confirmation or when `--apply` is present.

See Google's [desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app) and [Gmail scope descriptions](https://developers.google.com/workspace/gmail/api/auth/scopes).

Tokens default to `~/.config/contacts-cli/token.json`. Use `--token /outside/git/token.json` after
the subcommand on `authorize`, `sender-sync`, and `duplicate` commands to select another token/account. A
contact URL's `/u/0/` or `/u/1/` segment does **not** select the API account; the token does.

Token writes are atomic, with owner-only file permissions on POSIX systems. The CLI rejects client
and token paths inside a Git worktree, including resolved symlinks. Keep downloaded clients, tokens,
and backups outside Git. Never paste their contents into issues or logs. Repository ignore rules are
an additional safeguard, not secret detection.

Ordinary runs refresh saved credentials without a browser. If the token file is missing,
`sender-sync` and `duplicate` list authorization options. In an interactive terminal it asks
`Authorize now in your browser? [y/N]`. Only `y` or `yes` starts authorization with the default
client file; on success the original command resumes, including `--apply` if supplied. Declining or
reaching end-of-input exits with code 1. Noninteractive runs show the options and exit without
prompting. A custom `--token` path is preserved through authorization and in the suggested commands.

The default client file must already exist. For a different client file or manual browser opening,
use the listed standalone `authorize` commands and rerun sender-sync. Invalid or revoked tokens
still require explicit authorization; other errors do not trigger the missing-token prompt. Google
documents that external apps in Testing mode generally receive refresh tokens valid for seven days
with these scopes; see [token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## Upgrading an existing authorization

If you previously authorized `gmail.metadata`, update [Data Access](https://console.cloud.google.com/auth/scopes) to include
`https://www.googleapis.com/auth/gmail.readonly` alongside the contacts scope, using **Add or Remove
Scopes → Manually add scopes → Add to table → Update → Save**. The Desktop client file stays the same.

The CLI checks saved permissions before refreshing or making API requests. If permissions are
insufficient, it explains the new Gmail permission, lists authorization options, and asks
`Reauthorize now in your browser? [y/N]` in an interactive terminal. Answer `y` or `yes` to authorize
and resume the original command. Enter, `n`, or end-of-input exits without changing contacts or the
existing token. Noninteractive runs print the authorization command and exit without prompting.

A successful authorization replaces the saved token only after checking the required scopes and
refresh token. A denied, timed-out, or incomplete authorization leaves the existing token intact.
Alternatively, run `./contacts-cli authorize` explicitly. Other token errors do not trigger this
permission-upgrade prompt.
