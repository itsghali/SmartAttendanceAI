import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { CheckInScreen } from "../screens/CheckInScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { restoreSession } from "../store/authSlice";
import { useAppDispatch, useAppSelector } from "../store/hooks";

const Stack = createNativeStackNavigator();

export function RootNavigator() {
  const dispatch = useAppDispatch();
  const status = useAppSelector((state) => state.auth.status);

  useEffect(() => {
    dispatch(restoreSession());
  }, [dispatch]);

  if (status === "idle" || status === "loading") {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {status === "authenticated" ? (
          <Stack.Screen name="CheckIn" component={CheckInScreen} />
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
