export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002",
  demoOtp: process.env.NEXT_PUBLIC_DEMO_OTP === "true",
};
