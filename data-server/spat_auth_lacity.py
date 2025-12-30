import asyncio
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from signalrcore.hub_connection_builder import HubConnectionBuilder

async def main():
    try:
        json_path = "atsar-authen-dc26bc2a3ba4.json"
        audience = "https://arykoe7at-sacuz.info/atsac_api"
        hub_url = f"{audience}/atsachub"

        credentials = service_account.IDTokenCredentials.from_service_account_file(
            json_path,
            target_audience=audience
        )
        request = Request()
        credentials.refresh(request)
        id_token = credentials.token

        if not id_token:
            print("ID token is null.")
            return

        connection = HubConnectionBuilder() \
            .with_url(hub_url, options={
                "access_token_factory": lambda: id_token,
                "verify_ssl": False
            }) \
            .with_automatic_reconnect({
                "type": "raw",
                "keep_alive_interval": 10,
                "reconnect_interval": 5,
                "max_attempts": 9999
            }) \
            .build()

        connection.on("ReceiveData", lambda args: print("Received:", args[0]))

        connection.start()
        print("Connected. Listening for updates...")
        await asyncio.Event().wait()

    except Exception as e:
        print("Exception:", e)

if __name__ == "__main__":
    asyncio.run(main())
