import { StatusBar } from "expo-status-bar";
import { Provider } from "react-redux";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { RootNavigator } from "./src/navigation/RootNavigator";
import { setSessionExpiredHandler } from "./src/services/api";
import { sessionExpired } from "./src/store/authSlice";
import { store } from "./src/store/store";

setSessionExpiredHandler(() => store.dispatch(sessionExpired()));

export default function App() {
  return (
    <Provider store={store}>
      {/* The navigator runs with headerShown: false, so nothing else inflates
          the status bar / notch area. Without this the top row of every screen
          sits under the notch and its buttons cannot be tapped. */}
      <SafeAreaProvider>
        <RootNavigator />
        <StatusBar style="auto" />
      </SafeAreaProvider>
    </Provider>
  );
}
