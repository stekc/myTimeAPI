
# myTimeAPI

This is a fork of [versionDefect/myGoogleCalendar](https://github.com/versionDefect/myGoogleCalendar) that replaces Google Calendar integration with FastAPI. Combined with Siri Shortcuts you can automatically update your iCloud Calendar, ask Siri when your next shift is, etc.

For setup instructions, see the [original README](https://github.com/versionDefect/myGoogleCalendar/blob/main/README.md#the-hardest-part).

If you are unable to setup multifactor authentication (not at work for example) you can set `headless` to `False` in the config and manually login from the browser. This is a temporary solution as eventually you will be required to login again and provide the verification code sent over SMS.

![](https://i.postimg.cc/mbwsHKrH/image.png)