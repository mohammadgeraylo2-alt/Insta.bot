from rubpy import Client
import asyncio

async def main():
    print("=" * 40)
    print("   گرفتن Session String روبیکا")
    print("=" * 40)
    
    phone = input("\n📱 شماره‌ات رو وارد کن (مثلاً +989123456789): ").strip()
    
    app = Client("rubika_session", phone_number=phone)
    
    async with app:
        session_string = await app.export_session_string()
        print("\n" + "=" * 40)
        print("✅ Session String گرفته شد!")
        print("=" * 40)
        print("\n🔑 این مقدار رو کپی کن و توی Railway با نام SESSION_STRING بذار:\n")
        print(session_string)
        print("\n" + "=" * 40)
        print("⚠️  این string رو به کسی نده! مثل پسورد مهمه.")
        print("=" * 40)

asyncio.run(main())
